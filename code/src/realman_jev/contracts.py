"""The policy boundary contains sensor evidence, never simulator task state."""
from dataclasses import dataclass
from typing import Literal
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


Predicate = Literal["visible", "aligned", "at_grasp_height", "gripper_closed", "holding", "lifted", "above_destination", "lowered", "released", "retreated", "object_in_destination"]


class Stage(Strict):
    id: str = Field(min_length=1, max_length=60)
    objective: str = Field(min_length=1, max_length=600)
    focus: Literal["object", "destination", "gripper", "scene"]
    completion: list[Predicate] = Field(min_length=1, max_length=6)
    maintain: list[Predicate] = Field(default_factory=list, max_length=6)
    constraints: list[str] = Field(max_length=8)
    recovery: str = Field(min_length=1, max_length=500)
    max_decisions: int = Field(ge=1, le=100)


class Plan(Strict):
    task: str = Field(min_length=1, max_length=1000)
    object_label: str = Field(min_length=1, max_length=100)
    destination_label: str = Field(min_length=1, max_length=100)
    stages: list[Stage] = Field(min_length=1, max_length=16)
    @model_validator(mode="after")
    def unique(self):
        if len({s.id for s in self.stages}) != len(self.stages):
            raise ValueError("Stage IDs must be unique")
        return self


@dataclass
class CameraFrame:
    name: str
    rgb: np.ndarray
    depth: np.ndarray
    K: np.ndarray
    T_base_camera: np.ndarray | None
    captured: float


@dataclass
class Observation:
    sequence: int
    captured: float
    tcp: np.ndarray
    rotation: np.ndarray
    joints: np.ndarray
    aperture: float
    cameras: dict[str, CameraFrame]
    grasp_point: np.ndarray


class Decision(Strict):
    action: str
    transition: Literal["continue", "advance", "replan", "stop"]
    confidence: float = Field(ge=0, le=1)
    transition_confidence: float = Field(ge=0, le=1)


def actions(coarse, fine):
    catalog = {"hold": {"delta": [0., 0., 0.], "gripper": "hold"},
               "open": {"delta": [0., 0., 0.], "gripper": "open"},
               "close": {"delta": [0., 0., 0.], "gripper": "close"}}
    for i, axis in enumerate("xyz"):
        for sign, value in (("negative", -1), ("positive", 1)):
            for scale, step in (("coarse", coarse), ("fine", fine)):
                delta = [0., 0., 0.]
                delta[i] = value * step
                catalog[f"{axis}_{sign}_{scale}"] = {"delta": delta, "gripper": "hold"}
    return catalog
