# Brightloop Subscription Management System

A unified subscription management and recurring billing platform built for the Odoo Hackathon.

## Quickstart (3-Command Setup)

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run migrations
python manage.py migrate

# 3. Start development server
python manage.py runserver
```

## Seed Demo Data

```bash
python manage.py seed_demo --customers 80 --subs 200 --reset
```

### Demo Accounts
- **Admin**: `admin@brightloop.test` / `Demo@12345`
- **Staff**: `staff@brightloop.test` / `Demo@12345`
- **Customer**: `customer@brightloop.test` / `Demo@12345`
