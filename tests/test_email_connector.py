from digital_estate_manager.discovery import connect_email_provider


def test_connect_email_provider():
    # 1. Test Gmail connection interface
    res_gmail = connect_email_provider(provider="gmail", email_address="alex@gmail.com")
    assert res_gmail["success"] is True
    assert res_gmail["provider"] == "gmail"
    assert res_gmail["status"] == "ready_for_auth"
    assert "https://accounts.google.com" in res_gmail["auth_url"]

    # 2. Test unsupported provider rejection
    res_outlook = connect_email_provider(provider="outlook", email_address="alex@outlook.com")
    assert res_outlook["success"] is False
    assert res_outlook["status"] == "unsupported"


if __name__ == "__main__":
    test_connect_email_provider()
    print("EMAIL CONNECTOR INTERFACE TESTS PASSED!")
