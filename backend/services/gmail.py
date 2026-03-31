import base64

import requests


def send_email(access_token: str, to: str, subject: str, body: str) -> dict:
    message = f"To: {to}\r\nSubject: {subject}\r\n\r\n{body}"
    encoded = base64.urlsafe_b64encode(message.encode()).decode()

    url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    response = requests.post(url, headers=headers, json={"raw": encoded}, timeout=30)

    if response.status_code != 200:
        raise Exception(f"Gmail send failed: {response.text}")

    return response.json()
