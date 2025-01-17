import random
import smtplib
from email.mime.text import MIMEText

# 인증번호 생성 함수
def generate_verification_code():
    return str(random.randint(100000, 999999))

# 이메일 전송 함수
def send_verification_email(email: str, code: str):
    smtp_server = "smtp.yourdomain.com"
    smtp_port = 587
    sender_email = "no-reply@yourdomain.com"
    sender_password = "your_password"

    message = MIMEText(f"인증번호: {code}")
    message["Subject"] = "비밀번호 복구 인증번호"
    message["From"] = sender_email
    message["To"] = email

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, email, message.as_string())
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False