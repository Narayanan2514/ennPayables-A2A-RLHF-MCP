def pair_docs(remit_row, bank_row):
    """
    Central pairing logic between Remittance and Bank Doc
    """
    print("🔗 MATCH FOUND")
    print(f"  Remit ID : {remit_row['h_id']}")
    print(f"  Bank ID  : {bank_row['b_id']}")
