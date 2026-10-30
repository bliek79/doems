"""Freeze unchanged Alpha53 strategy algorithms independently of new wiring."""
import ast
import hashlib
import json
from pathlib import Path

EXPECTED = {'_finite': '6d8261abad254fd2aafa512c36b2f7fea25fca0cd29502ee7001963ac847de47', '_time': '61cbb1dbba3cacceee667d5ce25bdb5edef9062e531cf6edff6fb644b4e1ed72', '_ceil_quarter': '35a18e939535fb28062aaa0aeb2b2cf0198c009b3573b0b3d1a89d0ab2abdbc1', '_empty': '1b64e0027c3d99d1aa9b182f41ea74191eb9bba14bc113c2fa93cb6bc73c515e', '_Battery': 'ee7f3c83194244ae7a77394e8759f55441e292d5b6b6bc707fcddd6d9f650251', '_Window': '8512f7119fddfdccc6b13ab663428bbb2eb495b4f8aee8fb7fcdfbc8fab9162f', '_source': '0c96c7a7cb8da822d361286aa5a54f7a0a9d1436c1521dc6343e04e4d2831576', '_Model.__init__': '4a31d93ca27fb2c21b941bbc17da0351929b9366d9cdbc32de1b81e6e2987dae', '_need': 'b26f543a15d9092efbe389af21eb4b4101dbc8d163671d4e15cb855ced0514b5', '_remaining_battery_need': '57dec2fdc1a47df70ddd348d695bee2411876fef7eaad620f633ba3c5aff76ac', '_protected_ceiling': '2b131c32f28ca521a28aa7335ede05b6bc76100ae1f5c6bfeda91c035e787ada', '_safety_schedule': '63463c4bc735fd475a90def7e57499aa8b36dc5606105c7a124d91cad633d905', '_trade_schedule': '8f8c6c01f84d8756bf6039c6f42a9718ec53996abfe0496aa34d282cdba4067b', '_window_free': '8ab4e9e0d0a3f3f9890b7a696d172588e3d4d9eeeea10394062402c4a27336e8', '_safety_windows': '765bc744a3d9d2c71653f5f617611e81424fcb226463d74c41e176e81120df9b', '_trade_windows': '1e377211486abc524cb6c4f06c2431e319eb1801ee9476f943d0209bd3fc4ec6', '_compact_windows': 'd1badc85322de9f07511241d59b144e1e5aa9d649b19c26e2673526a9dea1c24', '_describe_windows': 'c88f13181f897965be7ef5437e39072eb2820b8cf22168705343afd19d0bdbb5', 'calculate_plan72': '6a5355fc2eabe5ebe35973842dc0cc765d8ea21cba4e9dba8d69d51c5aec3475'}


def canonical(node):
    if isinstance(node, ast.AST):
        return [type(node).__name__, {key: canonical(value) for key, value in ast.iter_fields(node)
                                     if value is not None and value != []}]
    if isinstance(node, list):
        return [canonical(item) for item in node]
    return node


def digest(node):
    return hashlib.sha256(json.dumps(canonical(node), sort_keys=True).encode()).hexdigest()


def test_ch7_preserves_unmodified_alpha53_algorithms():
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
    assert actual == EXPECTED
