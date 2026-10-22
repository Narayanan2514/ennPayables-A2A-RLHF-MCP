import pandas as pd

# def decode_fields(mapping_path: str, encrypted_fields: dict) -> dict:
#     decoded_data = {}

#     try:
#         df = pd.read_excel(mapping_path)

#         # Updated column check
#         if "Encrypted Word" not in df.columns or "Original Word" not in df.columns:
#             raise ValueError("Mapping file must contain 'Encrypted Word' and 'Original Word' columns")

#         # Build mapping: code → word
#         mapping = {
#             str(code).zfill(3): str(word)
#             for code, word in zip(df["Encrypted Word"], df["Original Word"])
#         }

#         for key, value in encrypted_fields.items():
#             raw = str(value).strip().replace(" ", "")

#             if not raw or len(raw) % 3 != 0:
#                 decoded_data[key] = value
#                 continue

#             decoded_words = []
#             valid = True

#             for i in range(0, len(raw), 3):
#                 code = raw[i:i + 3]
#                 if code not in mapping:
#                     valid = False
#                     break
#                 decoded_words.append(mapping[code])

#             decoded_data[key] = " ".join(decoded_words) if valid else value

#     except Exception as e:
#         print(f"⚠️ Decoder failed, fallback to raw values: {e}")
#         return encrypted_fields.copy()

#     return decoded_data


# def decode_fields(mapping_path: str, encrypted_fields: dict) -> dict:
#     decoded_data = {}

#     try:
#         df = pd.read_excel(mapping_path)

#         # Validate required columns
#         if "Encrypted Word" not in df.columns or "Original Word" not in df.columns:
#             raise ValueError(
#                 "Mapping file must contain 'Encrypted Word' and 'Original Word' columns"
#             )

#         # Build mapping: code -> word
#         mapping = {
#             str(code).strip(): str(word)
#             for code, word in zip(df["Encrypted Word"], df["Original Word"])
#         }

#         for key, value in encrypted_fields.items():

#             # Keep spaces intact
#             tokens = str(value).strip().split()

#             decoded_tokens = []

#             for token in tokens:

#                 token = token.strip()

#                 # Decode:
#                 # - 3 digit codes
#                 # - single digit codes
#                 if (
#                     token.isdigit()
#                     and (len(token) == 3 or len(token) == 1)
#                     and token in mapping
#                 ):
#                     decoded_tokens.append(mapping[token])

#                 else:
#                     # Keep unknown/non-numeric tokens as-is
#                     decoded_tokens.append(token)

#             # Preserve spaces between tokens
#             decoded_data[key] = " ".join(decoded_tokens)

#     except Exception as e:
#         print(f"⚠️ Decoder failed, fallback to raw values: {e}")
#         return encrypted_fields.copy()

#     return decoded_data


def decode_fields(mapping_path: str, encrypted_fields: dict) -> dict:
    decoded_data = {}

    try:
        df = pd.read_excel(mapping_path)

        # Validate required columns
        if "Encrypted Word" not in df.columns or "Original Word" not in df.columns:
            raise ValueError(
                "Mapping file must contain 'Encrypted Word' and 'Original Word' columns"
            )

        # Build mapping: code -> word
        mapping = {
            str(code).strip(): str(word)
            for code, word in zip(df["Encrypted Word"], df["Original Word"])
        }

        for key, value in encrypted_fields.items():

            # keep spaces intact
            tokens = str(value).strip().split()

            decoded_tokens = []

            for token in tokens:
                token = token.strip()

                # decode:
                # - 3 digit numbers
                # - single digit numbers
                # - single alphabets
                # if (
                #     (token.isdigit() and len(token) in (1, 3))
                #     or (token.isalpha() and len(token) == 1)
                # ) and token in mapping:
                if ( (token.isdigit() and len(token) in (1, 3)) 
                    or (token.isalpha() and token.islower() and 
                        len(token) == 1) ) and token in mapping:

                    decoded_tokens.append(mapping[token])

                else:
                    decoded_tokens.append(token)

            decoded_data[key] = " ".join(decoded_tokens)

    except Exception as e:
        print(f"⚠️ Decoder failed, fallback to raw values: {e}")
        return encrypted_fields.copy()

    return decoded_data