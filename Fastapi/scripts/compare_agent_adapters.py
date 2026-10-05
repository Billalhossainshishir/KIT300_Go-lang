"""Report optional adapter availability without making a trust decision.

This only lists what is installed. The comparative experiment itself, two
agents on different models each going from free text to checkout, review or a
stop, is scripts/run_model_comparison.py.
"""
import json
from ramify.agent.langgraph_adapter import LangGraphAdapter
from ramify.agent.pydanticai_adapter import PydanticAIAdapter

rows=[]
for adapter in (LangGraphAdapter(), PydanticAIAdapter()):
    rows.append({
        "adapter": adapter.name,
        "available": adapter.available(),
        "allowed_capabilities": ["interpret_known_catalogue_item", "explain_sealed_receipt"],
        "forbidden_capabilities": ["set_posture", "write_reason_code", "authorise_action", "modify_receipt"],
    })
print(json.dumps({"comparison": rows, "selected_for_demo": "LangGraphAdapter"}, indent=2))
