"""Freeze reviewed Plan72 strategies; approved H8 delta after Alpha84 parity review."""
import ast
import hashlib
import json
from pathlib import Path

EXPECTED = {'_finite': '6d8261abad254fd2aafa512c36b2f7fea25fca0cd29502ee7001963ac847de47', '_time': '61cbb1dbba3cacceee667d5ce25bdb5edef9062e531cf6edff6fb644b4e1ed72', '_ceil_quarter': '35a18e939535fb28062aaa0aeb2b2cf0198c009b3573b0b3d1a89d0ab2abdbc1', '_empty': 'ab2620f684d908f5c7f7803d5f57089347b7af9dc9e13b3110b1cecd8af34148', '_Battery': 'ee7f3c83194244ae7a77394e8759f55441e292d5b6b6bc707fcddd6d9f650251', '_Window': '1c894fa7bb6daf78b8c6e72440b8323648b5e854eb85afe6d1baa1caf33963b3', '_source': '0c96c7a7cb8da822d361286aa5a54f7a0a9d1436c1521dc6343e04e4d2831576', '_Model.__init__': '4a31d93ca27fb2c21b941bbc17da0351929b9366d9cdbc32de1b81e6e2987dae', '_need': 'b26f543a15d9092efbe389af21eb4b4101dbc8d163671d4e15cb855ced0514b5', '_remaining_battery_need': '57dec2fdc1a47df70ddd348d695bee2411876fef7eaad620f633ba3c5aff76ac', '_protected_ceiling': '2b131c32f28ca521a28aa7335ede05b6bc76100ae1f5c6bfeda91c035e787ada', '_safety_schedule': '63463c4bc735fd475a90def7e57499aa8b36dc5606105c7a124d91cad633d905', '_trade_schedule': '8f8c6c01f84d8756bf6039c6f42a9718ec53996abfe0496aa34d282cdba4067b', '_window_free': '8ab4e9e0d0a3f3f9890b7a696d172588e3d4d9eeeea10394062402c4a27336e8', '_safety_windows': 'ab52060b94329c52094541c4e2c44179e2898bbb02c05e6b2d0780416c191ca7', '_trade_windows': 'eaaee99e6d0ec5590b9112915b798e369c190d00ac693b793006e98001161673', '_group_action_windows': '3ccd0cc53865d2aff6dda972d9eca6bc8728aff7f6b3f182bb0d5921ffcfee03', '_describe_windows': '7d764a4ae5b799565ae616bc1d958a634744c1303d05bb09e6fe844c9b0c4dfb', 'calculate_plan72': 'e4defa4490b07753f3c125b50423f4df4d342c351894613f11a04c55251e723b', '_reconcile_alpha84_physical_safety': 'de20ca43bfc7ed8aa34701c59d735d3136f3e4bfccfaf66d2de991250820c689'}


def canonical(node):
    if isinstance(node, ast.AST):
        return [type(node).__name__, {key: canonical(value) for key, value in ast.iter_fields(node)
                                     if value is not None and value != []}]
    if isinstance(node, list):
        return [canonical(item) for item in node]
    # Runtime typing annotations may contain `tuple[T, ...]`. Preserve the
    # literal ellipsis in the AST digest instead of raising a JSON TypeError;
    # frozen reviewed hashes still MUST be compared and will stay red until
    # the changed production algorithms are substantively reviewed.
    if node is Ellipsis:
        return '...'
    return node


def digest(node):
    return hashlib.sha256(json.dumps(canonical(node), sort_keys=True).encode()).hexdigest()


def test_ch7_preserves_reviewed_strategy_algorithms():
    source = Path(__file__).resolve().parents[1] / 'custom_components/doems/planner_72h.py'
    actual = {}
    for node in ast.parse(source.read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            if isinstance(node, ast.ClassDef) and node.name == '_Model':
                for method in node.body:
                    if isinstance(method, ast.FunctionDef) and method.name != 'simulate':
                        actual['_Model.' + method.name] = digest(method)
            elif node.name not in {'_manual_inputs', '_Manual'}:
                actual[node.name] = digest(node)
    # Fifteen unchanged H7 digests remain frozen; the four reviewed H8 nodes
    # are locked to explicit static hashes. Mixed simulator logic is checked below.
    assert actual == EXPECTED


def test_h8_mixed_flow_simulator_is_frozen_after_code_review():
    # H7 did not freeze _Model.simulate: H8 changes split one mixed physical
    # charge into distinct source safety and trade energy flows. Cover it now.
    source = Path(__file__).resolve().parents[1] / 'custom_components/doems/planner_72h.py'
    for node in ast.parse(source.read_text()).body:
        if isinstance(node, ast.ClassDef) and node.name == '_Model':
            for method in node.body:
                if isinstance(method, ast.FunctionDef) and method.name == 'simulate':
                    assert digest(method) == '36a513e4c7bca0b5600b50eb7d68120f35792c09ec502ab79ce13f32fe6b251b'
                    return
    raise AssertionError('Plan72 simulation implementation missing')
