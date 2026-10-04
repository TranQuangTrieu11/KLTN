"""Provision an administrator locally; customer registration grants no admin access."""
import argparse
import getpass
from customer_accounts import Accounts
from agent_server import EXTENSIONS


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Tạo hoặc đặt lại tài khoản quản trị')
    parser.add_argument('--username', '--email', dest='email', default='admin')
    args = parser.parse_args()
    password = getpass.getpass('Mật khẩu quản trị: ')
    if password != getpass.getpass('Nhập lại mật khẩu: '):
        raise SystemExit('Mật khẩu không khớp.')
    Accounts(EXTENSIONS).provision_admin(args.email, password)
    print('Đã thiết lập tài khoản quản trị: '+args.email)
