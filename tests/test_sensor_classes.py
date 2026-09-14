from custom_components.cellar_tracker import sensor
from homeassistant.components.sensor.const import DEVICE_CLASS_STATE_CLASSES


def test_every_scalar_uses_a_valid_device_and_state_class_pairing():
    # HA logs a warning per entity for an invalid pairing, and its own code
    # comment says this should raise in a future release. This is the defect
    # the rewrite exists to fix.
    for key, _name, device_class, state_class, _unit, _icon in sensor.SCALAR_SPECS:
        if device_class is None:
            continue
        allowed = DEVICE_CLASS_STATE_CLASSES[device_class]
        assert state_class in allowed, (
            f"{key}: {state_class} invalid for {device_class}, allowed: {allowed}"
        )


def test_slice_sensors_exclude_items_from_the_recorder():
    # Without this the recorder blanks the entity's whole attribute dict.
    assert "items" in sensor.CellarSliceSensor._unrecorded_attributes
