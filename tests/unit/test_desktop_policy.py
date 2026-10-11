import pytest
from pydantic import ValidationError

from relayforge.desktop.policy import (
    Control,
    ControlRequest,
    EmptyRequest,
    InspectRequest,
    KeysRequest,
    TypeRequest,
    ValueRequest,
    parse_request,
    requires_path_approval,
)


def test_control_validation():
    with pytest.raises(ValidationError):
        Control()
    with pytest.raises(ValidationError):
        Control(control_type="Invalid Type!")
    valid = Control(name="OK", control_type="Button")
    assert valid.name == "OK"


def test_request_schemas():
    inspect_data = InspectRequest(depth=2, limit=50)
    assert inspect_data.depth == 2

    with pytest.raises(ValidationError):
        InspectRequest(depth=5)

    ctrl_req = ControlRequest(control=Control(name="Submit"))
    assert ctrl_req.control.name == "Submit"

    val_req = ValueRequest(control=Control(name="Field"), value="hola")
    assert val_req.value == "hola"

    type_req = TypeRequest(text="escribe esto")
    assert type_req.text == "escribe esto"

    with pytest.raises(ValidationError):
        KeysRequest(chord="alt+f5")  # not allowed
    keys_req = KeysRequest(chord="ctrl+s")
    assert keys_req.chord == "ctrl+s"

    empty = EmptyRequest()
    assert empty.model_dump() == {}


def test_parse_request():
    parsed = parse_request("desktop_keys", '{"chord": "enter"}')
    assert parsed == {"chord": "enter"}

    with pytest.raises(ValueError):
        parse_request("invalid_kind", "{}")

    with pytest.raises(ValueError):
        parse_request("desktop_keys", '{"chord": "invalid"}')


def test_requires_path_approval(tmp_path):
    allowed_dir = tmp_path / "desktop-files"
    allowed_dir.mkdir()
    valid_file = allowed_dir / "doc.txt"

    # Plain text without paths does not require approval
    assert not requires_path_approval("desktop_type", {"text": "just simple text"}, (allowed_dir,))

    # Allowed path requires approval
    assert requires_path_approval("desktop_type", {"text": str(valid_file)}, (allowed_dir,))

    # Outside path is rejected
    outside = tmp_path / "outside.txt"
    with pytest.raises(ValueError, match="desktop_path_rejected"):
        requires_path_approval("desktop_type", {"text": str(outside)}, (allowed_dir,))

    # Traversal path rejected
    traversal = str(allowed_dir) + "/../secret.txt"
    with pytest.raises(ValueError, match="desktop_path_rejected"):
        requires_path_approval("desktop_type", {"text": traversal}, (allowed_dir,))


def test_menu_request_is_bounded_and_strict():
    assert parse_request("desktop_menu", '{"path": ["Archivo", "Guardar como..."]}') == {
        "path": ["Archivo", "Guardar como..."]
    }
    from relayforge.desktop.policy import DesktopPolicyError

    for raw in (
        '{"path": []}',
        '{"path": ["a", "b", "c", "d", "e"]}',
        '{"path": [""]}',
        '{"path": "Archivo"}',
        '{"path": ["x"], "id": 4}',
    ):
        with pytest.raises(DesktopPolicyError):
            parse_request("desktop_menu", raw)
