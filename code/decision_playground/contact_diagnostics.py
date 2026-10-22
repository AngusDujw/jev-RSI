"""Opt-in startup-only contact reporting for outer controlled diagnostics.

Only reporting API/threshold opinions are authored in the runtime session
layer, with a process-local reporting gate enabled after SimulationContext.
No shared USD file is saved and no collision/drive/sleep setting changes.
Import this module freely; enable() requires an already initialized Kit runtime.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys
import threading


class ContactDiagnostics:
    def __init__(self, output):
        self.output = Path(output).expanduser().resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.context = lambda: {"phase": "startup"}
        self.lock = threading.RLock()
        self.closed = False
        self.roots = []
        self.subscription = None
        self.config_module = None
        self.original_config = None
        self.wrapped_config = None
        self.processing_settings = None
        self.processing_captured = False
        self.processing_original = None
        self.meta = {"condition": "session-layer-contact-reports-v2",
                     "scope": "outer_only", "subscription_active": False,
                     "processing_enabled": False, "processing_original_value": None,
                     "processing_value_after": None, "processing_audits": [],
                     "enabled_prims": [], "spawned_roots": [],
                     "failures": [], "failure_count": 0, "callbacks": 0,
                     "owned_report_headers": 0,
                     "absence_semantics": "Missing reports are not proof of no contact.",
                     "protected_attribute_audits": []}
        self._persist_meta()

    def _persist_meta(self):
        try:
            path = self.output / "contact_reporting_meta.json"
            staging = path.with_name(path.name + ".writing")
            staging.write_text(json.dumps(self.meta, indent=2, allow_nan=False) + "\n")
            staging.replace(path)
        except Exception as error:
            print(f"Contact metadata persistence failed: {error}", file=sys.stderr, flush=True)

    def _failure(self, stage, error):
        with self.lock:
            self.meta["failure_count"] += 1
            self.meta["failures"].append({"stage": stage, "error": f"{type(error).__name__}: {error}"})
            self._persist_meta()

    def set_context(self, callback):
        if not callable(callback):
            raise TypeError("Contact context must be callable")
        self.context = callback
        return self

    def arm_processing(self):
        """Enable the process-local contact reporting gate after SimContext.

        IsaacLab sets this gate True while constructing SimulationContext. Arm
        after that initialization (at spawn and again after factory), preserving
        the first observed original value for conditional close restoration.
        """
        if self.closed:
            return False
        try:
            import carb.settings
            settings = carb.settings.get_settings()
            name = "/physics/disableContactProcessing"
            before = settings.get(name)
            if type(before) is not bool:
                raise RuntimeError("Contact processing gate has no explicit boolean value")
            if not self.processing_captured:
                self.processing_settings = settings
                self.processing_original = before
                self.processing_captured = True
                self.meta["processing_original_value"] = before
            settings.set_bool(name, False)
            after = settings.get(name)
            self.meta["processing_value_after"] = after
            self.meta["processing_enabled"] = after is False
            self.meta["processing_audits"].append({"before": before, "after": after})
            if after is not False:
                raise RuntimeError("Contact processing gate failed read-back verification")
            self._persist_meta()
            return True
        except Exception as error:
            self.meta["processing_enabled"] = False
            self._failure("arm_processing", error)
            return False

    @staticmethod
    def _protected(prim):
        return {a.GetName(): str(a.Get()) for a in prim.GetAttributes()
                if any(name in a.GetName().lower() for name in ("sleep", "collision", "drive:"))}

    def _enable_prim_tree(self, root):
        from pxr import PhysxSchema, Usd, UsdPhysics

        self.arm_processing()
        stage = root.GetStage()
        root_path = str(root.GetPath())
        if root_path not in self.roots:
            self.roots.append(root_path)
            self.meta["spawned_roots"].append(root_path)
        prims = list(Usd.PrimRange(root))
        before = {str(p.GetPath()): self._protected(p) for p in prims}
        with Usd.EditContext(stage, stage.GetSessionLayer()):
            for prim in prims:
                if not prim.HasAPI(UsdPhysics.RigidBodyAPI):
                    continue
                try:
                    api = PhysxSchema.PhysxContactReportAPI.Apply(prim)
                    if api.CreateThresholdAttr().Set(0.) is False:
                        raise RuntimeError("Runtime contact-report threshold could not be authored")
                    path = str(prim.GetPath())
                    if path not in self.meta["enabled_prims"]:
                        self.meta["enabled_prims"].append(path)
                except Exception as error:
                    self._failure("enable_prim:" + str(prim.GetPath()), error)
        after = {str(p.GetPath()): self._protected(p) for p in prims}
        unchanged = before == after
        self.meta["protected_attribute_audits"].append({"root": root_path, "unchanged": unchanged,
                                                         "prim_count": len(prims)})
        if not unchanged:
            self._failure("protected_attributes", RuntimeError("Sleep/collision/drive opinions changed"))
        if not any(path == root_path or path.startswith(root_path + "/")
                   for path in self.meta["enabled_prims"]):
            self._failure("enable_tree", RuntimeError("No rigid body reporting API enabled"))
        self._persist_meta()

    def _owns(self, path):
        return any(path == root or path.startswith(root + "/") for root in self.roots)

    def _callback(self, headers, data):
        if self.closed:
            return
        try:
            from pxr import PhysicsSchemaTools
            with self.lock:
                self.meta["callbacks"] += 1
                try:
                    # Copy before the simulator advances or caller mutates state.
                    context = json.loads(json.dumps(self.context(), allow_nan=False))
                except Exception as error:
                    self._failure("context", error)
                    context = {"context_unavailable": True}
                records = []
                for header in headers:
                    paths = {name: str(PhysicsSchemaTools.intToSdfPath(getattr(header, name)))
                             for name in ("actor0", "actor1", "collider0", "collider1")}
                    if not any(self._owns(path) for path in paths.values()):
                        continue
                    contacts = []
                    start, count = int(header.contact_data_offset), int(header.num_contact_data)
                    if start < 0 or count < 0 or start + count > len(data):
                        raise ValueError("Contact buffer range is invalid")
                    for index in range(start, start + count):
                        item = data[index]
                        contacts.append({"position": [float(x) for x in item.position],
                                         "normal": [float(x) for x in item.normal],
                                         "impulse": [float(x) for x in item.impulse],
                                         "separation": float(item.separation)})
                    records.append({"context": context, "report_index": self.meta["callbacks"],
                                    "event_type": str(header.type), "stage_id": int(header.stage_id),
                                    **paths, "num_contact_data": count, "contacts": contacts,
                                    "impulse_semantics": "Raw per-physics-step impulse; not force."})
                if records:
                    encoded = [json.dumps(record, allow_nan=False) for record in records]
                    with (self.output / "contact_reports.jsonl").open("a") as stream:
                        stream.write("\n".join(encoded) + "\n")
                    self.meta["owned_report_headers"] += len(records)
                self._persist_meta()
        except Exception as error:
            self._failure("callback", error)

    def install(self):
        try:
            from omni.physx import get_physx_simulation_interface
            self.subscription = get_physx_simulation_interface().subscribe_contact_report_events(self._callback)
            if self.subscription is None:
                raise RuntimeError("Contact subscription returned no holder")
            self.meta["subscription_active"] = True
        except Exception as error:
            self._failure("subscribe", error)
        try:
            self.config_module = importlib.import_module("env.robot_manager.robot_config.x5")
            self.original_config = self.config_module.get_robot_config
            def config():
                value = self.original_config()
                try:
                    original_spawn = value.spawn.func
                    def spawn(*args, **kwargs):
                        # Original exceptions and return identity remain untouched.
                        root = original_spawn(*args, **kwargs)
                        if not self.closed:
                            try:
                                self._enable_prim_tree(root)
                            except Exception as error:
                                self._failure("spawn_report_enable", error)
                        return root
                    value.spawn = value.spawn.replace(func=spawn)
                except Exception as error:
                    self._failure("wrap_spawn_configuration", error)
                return value
            self.wrapped_config = config
            self.config_module.get_robot_config = config
        except Exception as error:
            self._failure("install_spawn_hook", error)
        self._persist_meta()
        return self

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.config_module is not None and self.config_module.get_robot_config is self.wrapped_config:
            self.config_module.get_robot_config = self.original_config
        if self.subscription is not None:
            try:
                unsubscribe = getattr(self.subscription, "unsubscribe", None)
                if unsubscribe is not None:
                    unsubscribe()
            except Exception as error:
                self._failure("unsubscribe", error)
            self.subscription = None
        if self.processing_captured:
            try:
                name = "/physics/disableContactProcessing"
                current = self.processing_settings.get(name)
                if current is False:
                    self.processing_settings.set_bool(name, self.processing_original)
                    restored = self.processing_settings.get(name)
                    self.meta["processing_restore_value"] = restored
                    if restored is not self.processing_original:
                        raise RuntimeError("Contact processing gate restoration failed verification")
                else:
                    self.meta["processing_restore_skipped_external_change"] = True
                    self.meta["processing_restore_value"] = current
            except Exception as error:
                self._failure("restore_processing", error)
        self.meta["subscription_active"] = False
        self.meta["closed"] = True
        self._persist_meta()

    restore = close


def enable(output):
    """Install before create_eval_env constructs X5; return a lifetime holder."""
    return ContactDiagnostics(output).install()
