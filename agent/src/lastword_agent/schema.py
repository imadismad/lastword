"""Strict JSON schema for the isolated reader's output (FR-02).

The reader is in quarantine: it has no tools and emits ONLY this schema. Any output
outside the schema is rejected. Each extracted field keeps its provenance (where in
the document it came from). A hidden instruction in the quote becomes a risk
indicator (injection_suspected), never an order.
"""

READER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["supplier_name", "beneficiary", "amount", "currency",
                 "quote_ref", "fields_provenance", "risk_signals"],
    "properties": {
        "supplier_name": {"type": "string", "maxLength": 200},
        "beneficiary": {
            # the payment address found in the document (may be bogus / attacker-controlled)
            "type": "string", "maxLength": 100,
        },
        "amount": {"type": "integer", "minimum": 0},
        "currency": {"type": "string", "maxLength": 10},
        "quote_ref": {"type": "string", "maxLength": 100},
        "validity": {"type": ["string", "null"], "maxLength": 60},
        "fields_provenance": {
            # for each field, where in the doc it was read from (page:line / span)
            "type": "object",
            "additionalProperties": {"type": "string", "maxLength": 60},
        },
        "risk_signals": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "injection_suspected": {"type": "boolean"},
                "hidden_instruction_text": {"type": ["string", "null"], "maxLength": 500},
                "new_beneficiary": {"type": "boolean"},
                "external_origin": {"type": "boolean"},
                "address_changed": {"type": "boolean"},
                "urgency_pressure": {"type": "boolean"},
            },
            "required": ["injection_suspected"],
        },
    },
}
