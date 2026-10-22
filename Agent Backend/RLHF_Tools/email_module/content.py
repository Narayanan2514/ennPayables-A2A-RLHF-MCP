def generate_voucher_approval_body(approver_name, ref_id):
    return f"""
<p>Hi {approver_name},</p>

<p>
  A voucher has been created and requires your <b>manual approval</b>
  before further processing can continue.
</p>

<table style="border-collapse: collapse; width: 50%; margin-top: 10px;">
  <tr>
    <td style="border: 1px solid #ddd; padding: 8px;">
      <b>Reference Number</b>
    </td>
    <td style="border: 1px solid #ddd; padding: 8px;">
      {ref_id}
    </td>
  </tr>
  <tr>
    <td style="border: 1px solid #ddd; padding: 8px;">
      <b>Status</b>
    </td>
    <td style="border: 1px solid #ddd; padding: 8px; color: orange;">
      <b>Pending Approval</b>
    </td>
  </tr>
</table>

<p style="margin-top: 15px;">
  Kindly review and approve the voucher at your earliest convenience.
</p>

<p>
  You can approve the request from the Exception tab in the application.
</p>

<br>

<p>
  Thanks & Regards,<br>
  <b>AI Ticketing System</b>
</p>
"""

def build_email_template(subject: str, body: str):

    formatted_body = body.replace("\n", "<br>")

    return f"""
    <html>
    <body style="
        font-family: Calibri, Arial, sans-serif;
        font-size: 14px;
        color: #000000;
        line-height: 1.6;
    ">

        <p>
            {formatted_body}
        </p>

    </body>
    </html>
    """