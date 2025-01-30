import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.message import EmailMessage
import os

# 인증번호 생성 함수
def generate_verification_code():
    return str(random.randint(100000, 999999))

# 비밀번호 복구 메일 
def send_verification_email(email: str, code: str):
    smtp_server = "smtp.gmail.com" # 받는 메일 
    smtp_port = 587
    sender_email = "ejji0001@gmail.com" # 보내는 메일
    sender_password = "defn mnnr cwdm xoms" # - 보안 문제 

    message = MIMEText(f"인증번호: {code}")
    message["Subject"] = "비밀번호 복구 인증번호"
    message["From"] = sender_email
    message["To"] = email

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, email, message.as_string())
        print("Email sent successfully")
        return True
    except smtplib.SMTPAuthenticationError as auth_error:
        print(f"Authentication failed: {auth_error}")
    except Exception as e:
        print(f"Failed to send email: {e}")
    return False

# 회원가입 인증 메일 
def send_signup_email(email: str, token: str):
    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    sender_email = "ejji0001@gmail.com"
    sender_password = "defn mnnr cwdm xoms"

    html_content = f"""
    <html>
        <body>
            <p>안녕하세요,</p>
            <p>회원가입을 완료하려면 아래 버튼을 클릭하여 이메일 인증을 완료하세요:</p>
            <a href="http://127.0.0.1:8000/signup/confirm?token={token}" 
               style="display:inline-block;padding:10px 20px;color:white;background-color:blue;text-decoration:none;border-radius:5px;">
               이메일 인증
            </a>
            <p>감사합니다!</p>
        </body>
    </html>
    """

    message = MIMEMultipart("alternative")
    message["Subject"] = "회원가입 이메일 인증"
    message["From"] = sender_email
    message["To"] = email
    message.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, email, message.as_string())
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False
    
def send_file_email(to_email: str, subject: str, body: str, attachment_path: str = None):
    """Send an email with an optional file attachment (CSV)."""
    smtp_server = "smtp.gmail.com" # 받는 메일 
    smtp_port = 587
    sender_email = "ejji0001@gmail.com" # 보내는 메일
    sender_password = "defn mnnr cwdm xoms"
    
    msg = EmailMessage()
    msg["From"] = sender_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    # ✅ Attach file if provided
    if attachment_path:
        try:
            with open(attachment_path, "rb") as file:
                msg.add_attachment(file.read(), maintype="application", subtype="octet-stream", filename=os.path.basename(attachment_path))
        except FileNotFoundError:
            raise ValueError(f"❌ File not found: {attachment_path}")

    # ✅ Send email
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()  # Secure connection
            server.login(sender_email, sender_password)  # Login
            server.send_message(msg)
        print(f"✅ Email sent to {to_email}")
    except Exception as e:
        print(f"❌ Email sending failed: {e}")