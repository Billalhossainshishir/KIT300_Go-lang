"""The tool surface a model is allowed to reach. Framework-neutral on purpose.

What is absent matters more than what is present: no tool sets a posture,
writes a reason code, chooses an action or seals a receipt. A model can ask
what a product is and ask for it to be assessed; the assessment comes back from
the engine already sealed. A hallucinated verdict has nowhere to enter.
"""

import copy

from ramify import engine
from ramify.data import seed


def list_products() -> list[dict]:
    """Every product in the demonstration catalogue."""
    return [
        {
            "subject_ref": ref,
            "name": record["name"],
            "brand": record["brand"],
            "category": record["category"],
            "gtin": record["identifiers"].get("gtin"),
        }
        for ref, record in seed.subjects().items()
    ]


def search_products(query: str, limit: int = 5) -> list[dict]:
    """Loose text search over the catalogue.

    Returning nothing is a valid answer the caller must handle — inventing a
    product to assess is worse than admitting the search found none.
    """
    terms = [t for t in query.lower().split() if len(t) > 2]
    scored = []
    for product in list_products():
        haystack = f"{product['name']} {product['brand']} {product['category']}".lower()
        score = sum(1 for term in terms if term in haystack)
        if score:
            scored.append((score, product))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["name"]))
    return [product for _, product in scored[:limit]]


def assess_product(identifier: str, actor_ref: str = "consumer_v1") -> dict:
    """Run the engine and return the sealed result.

    The receipt inside is already hashed and signed. A model may read it;
    anything it sends back is discarded.
    """
    return copy.deepcopy(engine.assess(identifier, actor_ref, context="agent_tool"))


TOOL_SPECS = [
    {
        "name": "search_products",
        "description": (
            "Find products in the catalogue matching a description. Returns "
            "candidates, possibly none. Never invent a product that is not "
            "returned by this tool."
        ),
        "parameters": {"query": "str", "limit": "int"},
        "callable": search_products,
    },
    {
        "name": "assess_product",
        "description": (
            "Run the trust assessment for one product and return a sealed "
            "decision receipt. This is the only source of a verdict. You must "
            "not state a posture, verdict or recommendation that did not come "
            "from this tool."
        ),
        "parameters": {"identifier": "str", "actor_ref": "str"},
        "callable": assess_product,
    },
    {
        "name": "list_products",
        "description": "List the full catalogue.",
        "parameters": {},
        "callable": list_products,
    },
]
