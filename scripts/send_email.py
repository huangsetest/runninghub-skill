"""
发送邮件工具 - 用于 RunningHub 生成图片后发送邮件
"""
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

def send_image_email(image_path, subject, body, to_email="aistudent2077@163.com"):
    """发送带图片附件的邮件"""
    with open(image_path, 'rb') as f:
        img_data = f.read()

    msg = MIMEMultipart()
    msg['From'] = 'aistudent2077@163.com'
    msg['To'] = to_email
    msg['Subject'] = subject

    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    img = MIMEImage(img_data)
    img.add_header('Content-Disposition', 'attachment', filename='generated_image.jpg')
    msg.attach(img)

    server = smtplib.SMTP_SSL('smtp.163.com', 465)
    server.login('aistudent2077@163.com', '<163邮箱授权码>')
    server.sendmail('aistudent2077@163.com', to_email, msg.as_string())
    server.quit()
    print(f"Email sent successfully to {to_email}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python send_email.py <image_path> <subject> [body]")
        sys.exit(1)

    image_path = sys.argv[1]
    subject = sys.argv[2]
    body = sys.argv[3] if len(sys.argv) > 3 else "Generated image"

    send_image_email(image_path, subject, body)
