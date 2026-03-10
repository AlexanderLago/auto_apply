import sqlite3
import time

# Wait for any locks to clear
time.sleep(3)

con = sqlite3.connect('data/auto_apply.db', timeout=30.0)
con.execute("PRAGMA journal_mode=WAL")
con.execute("PRAGMA busy_timeout=30000")

# Check what jobs exist
print("=== Current Jobs ===")
rows = con.execute("SELECT id, company, title, fit_score, status FROM jobs").fetchall()
for r in rows:
    print(f"  {r}")

# Insert Stripe job if not exists
print("\n=== Adding Stripe Job ===")
try:
    con.execute("""
        INSERT OR IGNORE INTO jobs 
        (source, external_id, title, company, location, work_type, url, 
         description_raw, skills_required, skills_nice, status, fit_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        'greenhouse',
        '5956528',
        'Strategy & Business Operations, Stripe Business Performance',
        'Stripe',
        'Remote',
        'Full-time',
        'https://stripe.com/jobs/listing/strategy-business-operations-stripe-business-performance/5956528/apply?gh_src=73vnei',
        'Strategy role at Stripe',
        '[]',
        '[]',
        'scored',
        95
    ))
    con.commit()
    print("Stripe job added/updated")
except Exception as e:
    print(f"Error: {e}")

# Verify and set highest score
print("\n=== Updating Scores ===")
con.execute("UPDATE jobs SET fit_score = 95 WHERE company = 'Stripe'")
con.execute("UPDATE jobs SET fit_score = 50 WHERE company = 'discord'")
con.commit()

# Show final queue
print("\n=== Job Queue (ordered) ===")
rows = con.execute("SELECT id, company, title, fit_score, status FROM jobs ORDER BY fit_score DESC").fetchall()
for r in rows:
    print(f"  Score {r[3]}: {r[1]} - {r[2][:50]}")

con.close()
