import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.message import EmailMessage
import os

# SMTP 설정 (보내는 사람)
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "ejji0001@gmail.com"  # 보내는 이메일
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
SENDER_NAME = "온길 - Ongil"  # 보내는 사람 이름


def send_email(to_email: str, subject: str, body: str, is_html: bool = False, attachment_path: str = None):
    """이메일 전송 함수 (텍스트/HTML/파일 첨부 가능)"""
    msg = EmailMessage()
    msg["From"] = f"{SENDER_NAME}"  # 보낸 사람 이름 설정
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body, subtype="html" if is_html else "plain")

    # 첨부 파일 추가
    if attachment_path:
        try:
            with open(attachment_path, "rb") as file:
                msg.add_attachment(file.read(), maintype="application", subtype="octet-stream", filename=os.path.basename(attachment_path))
        except FileNotFoundError:
            raise ValueError(f"❌ File not found: {attachment_path}")

    # SMTP 서버에 연결하여 이메일 전송
    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
        print(f"✅ Email sent to {to_email}")
        return True
    except smtplib.SMTPAuthenticationError as auth_error:
        print(f"❌ Authentication failed: {auth_error}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")
    return False


def generate_verification_code():
    """6자리 랜덤 인증번호 생성"""
    return str(random.randint(100000, 999999))


def send_verification_email(email: str, code: str):
    """비밀번호 복구 인증번호 이메일 전송"""
    subject = "비밀번호 복구 인증번호"
    body = f"인증번호: {code}"
    return send_email(email, subject, body)


def send_signup_email(email: str, token: str):
    """회원가입 이메일 인증 링크 전송"""
    subject = "회원가입 이메일 인증"
    html_content = f"""
    <html>
        <body>
            <p>안녕하세요,</p>
            <p>회원가입을 완료하려면 아래 버튼을 클릭하여 이메일 인증을 완료하세요:</p>
            <a href="http://127.0.0.1:8000/auth/signup/confirm?token={token}" 
               style="display:inline-block;padding:10px 20px;color:white;background-color:blue;text-decoration:none;border-radius:5px;">
               이메일 인증
            </a>
            <p>감사합니다!</p>
        </body>
    </html>
    """
    return send_email(email, subject, html_content, is_html=True)


def send_file_email(to_email: str, subject: str, body: str, attachment_path: str = None):
    """파일 첨부 이메일 전송"""
    return send_email(to_email, subject, body, attachment_path=attachment_path)