"""Decodes the vision LLM's extracted field values back from the 3-digit/
single-char codes agent_2.transform_service masked words with.

Exact port of ennVault_org_backend/modules/processing/entity_extractor/
decoder.py's `decode_fields`.
"""
from __future__ import annotations

import pandas as pd


def decode_fields(mapping_path: str, encrypted_fields: dict) -> dict:
    decoded_data = {}

    try:
        df = pd.read_excel(mapping_path)

        if "Encrypted Word" not in df.columns or "Original Word" not in df.columns:
            raise ValueError("Mapping file must contain 'Encrypted Word' and 'Original Word' columns")

        mapping = {str(code).strip(): str(word) for code, word in zip(df["Encrypted Word"], df["Original Word"])}

        for key, value in encrypted_fields.items():
            tokens = str(value).strip().split()
            decoded_tokens = []

            for token in tokens:
                token = token.strip()
                if (
                    (token.isdigit() and len(token) in (1, 3)) or (token.isalpha() and len(token) == 1)
                ) and token in mapping:
                    decoded_tokens.append(mapping[token])
                else:
                    decoded_tokens.append(token)

            decoded_data[key] = " ".join(decoded_tokens)

    except Exception:
        return encrypted_fields.copy()

    return decoded_data
