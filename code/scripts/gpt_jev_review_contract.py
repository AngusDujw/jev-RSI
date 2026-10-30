"""Task-independent, method-declared structured observation parameters.

This small JSON Schema subset checks data shape, not sensor truth or action safety.
No values are coerced and no missing observation is filled in by the host.
"""
import json
import math


TYPES = {"object", "array", "string", "boolean", "integer", "number", "null"}


def compile_fields(fields):
    """Normalize compact field descriptors into a strict object schema."""
    if not isinstance(fields, dict) or not 1 <= len(fields) <= 32:
        raise ValueError("Review fields must declare 1..32 named parameters")
    encoded = json.dumps(fields, allow_nan=False, ensure_ascii=False)
    if len(encoded) > 16384 or not encoded.isascii():
        raise ValueError("Review field declarations must be bounded English ASCII")
    count = [0]

    def compile_node(value, depth):
        count[0] += 1
        if depth > 8 or count[0] > 256:
            raise ValueError("Review field schema is too complex")
        if isinstance(value, str):
            value = {"type": value}
        elif isinstance(value, list):
            value = {"type": "string", "enum": value}
        if not isinstance(value, dict):
            raise ValueError("Expected a type name, string enum, or schema object")
        allowed = {"type", "description", "enum", "properties", "required", "additionalProperties",
                   "items", "minItems", "maxItems", "minimum", "maximum", "minLength", "maxLength"}
        if set(value)-allowed:
            raise ValueError("Unsupported review schema keyword")
        raw_type = value.get("type")
        types = raw_type if isinstance(raw_type, list) else [raw_type]
        if (not types or any(not isinstance(t, str) or t not in TYPES for t in types)
                or len(set(types)) != len(types) or len(types) > 2
                or (len(types) == 2 and "null" not in types)):
            raise ValueError("Expected one JSON type, optionally nullable")
        out = {"type": raw_type}
        if "description" in value:
            if not isinstance(value["description"], str) or len(value["description"]) > 2000:
                raise ValueError("Invalid review field description")
            out["description"] = value["description"]
        if "object" in types:
            props = value.get("properties")
            if not isinstance(props, dict) or len(props) > 32:
                raise ValueError("Objects need at most 32 declared properties")
            if any(not isinstance(k, str) or not k.isidentifier() or len(k) > 64 for k in props):
                raise ValueError("Review property names must be bounded identifiers")
            if "required" in value and (not isinstance(value["required"], list) or
                    any(not isinstance(k, str) for k in value["required"]) or
                    set(value["required"]) != set(props) or len(value["required"]) != len(props)):
                raise ValueError("All declared review properties are required")
            if value.get("additionalProperties", False) is not False:
                raise ValueError("Review objects cannot accept undeclared properties")
            out.update(properties={k: compile_node(v, depth+1) for k, v in props.items()},
                       required=list(props), additionalProperties=False)
        elif set(value) & {"properties", "required", "additionalProperties"}:
            raise ValueError("Object keywords require object type")
        if "array" in types:
            if "items" not in value:
                raise ValueError("Review arrays need an item schema")
            out["items"] = compile_node(value["items"], depth+1)
            out.update(minItems=0, maxItems=64)
        elif set(value) & {"items", "minItems", "maxItems"}:
            raise ValueError("Array keywords require array type")
        for low, high, valid_type, cap in (("minItems", "maxItems", "array", 64),
                                           ("minLength", "maxLength", "string", 6000)):
            if low in value or high in value:
                if valid_type not in types:
                    raise ValueError("Length keyword does not match field type")
                lo, hi = value.get(low, 0), value.get(high, cap)
                if type(lo) is not int or type(hi) is not int or not 0 <= lo <= hi <= cap:
                    raise ValueError("Invalid review field length bounds")
                out.update({low: lo, high: hi})
        if "string" in types and "maxLength" not in out:
            out["maxLength"] = 6000
        for key in ("minimum", "maximum"):
            if key in value:
                v = value[key]
                if not set(types) & {"number", "integer"} or type(v) not in (int, float) or not math.isfinite(v):
                    raise ValueError("Invalid numeric review bound")
                out[key] = v
        if "minimum" in out and "maximum" in out and out["minimum"] > out["maximum"]:
            raise ValueError("Reversed numeric review bounds")
        if "enum" in value:
            enum = value["enum"]
            if set(types) & {"object", "array"}:
                raise ValueError("Review enums are limited to primitive values")
            if not isinstance(enum, list) or not 1 <= len(enum) <= 32:
                raise ValueError("Review enum needs 1..32 values")
            for item in enum:
                validate_value(item, out)
            out["enum"] = json.loads(json.dumps(enum, allow_nan=False))
        return out

    return compile_node({"type": "object", "properties": fields}, 0)


def validate_value(value, schema, path="parameters"):
    """Validate exactly; notably true is neither an integer nor the string yes."""
    raw_type = schema["type"]
    types = raw_type if isinstance(raw_type, list) else [raw_type]
    actual = ("null" if value is None else "boolean" if type(value) is bool else
              "integer" if type(value) is int else "number" if type(value) is float else
              "string" if isinstance(value, str) else "array" if isinstance(value, list) else
              "object" if isinstance(value, dict) else "invalid")
    if actual not in types and not (actual == "integer" and "number" in types):
        raise ValueError(path+": wrong declared type")
    if actual in ("integer", "number"):
        if not math.isfinite(value) or value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            raise ValueError(path+": numeric value outside schema; actual="+repr(value)+
                ", minimum="+str(schema.get("minimum", "unbounded"))+
                ", maximum="+str(schema.get("maximum", "unbounded"))+"; value must be finite")
    if "enum" in schema and not any(
            (type(value) is type(v) or type(value) in (int, float) and type(v) in (int, float))
            and value == v for v in schema["enum"]):
        raise ValueError(path+": value outside declared enum")
    if actual == "object":
        props = schema["properties"]
        if set(value) != set(props):
            raise ValueError(path+": missing or undeclared fields")
        for key, item in value.items():
            validate_value(item, props[key], path+"."+key)
    elif actual in ("array", "string"):
        low, high = ("minItems", "maxItems") if actual == "array" else ("minLength", "maxLength")
        if not schema.get(low, 0) <= len(value) <= schema.get(high, math.inf):
            raise ValueError(path+": length outside schema (actual="+str(len(value))+
                ", min="+str(schema.get(low, 0))+", max="+
                str(schema.get(high, "unbounded"))+")")
        if actual == "array":
            for i, item in enumerate(value):
                validate_value(item, schema["items"], path+"["+str(i)+"]")
