# Quick status check for background apply run
import sqlite3
from datetime import datetime

config_db_path = "data/auto_apply.db"

try:
    con = sqlite3.connect(config_db_path, timeout=5.0)
    con.row_factory = sqlite3.Row
    
    # Count applications today
    today = datetime.now().date().isoformat()
    today_count = con.execute("""
        SELECT COUNT(*) FROM applications 
        WHERE date(applied_at) = ?
    """, (today,)).fetchone()[0]
    
    # Recent applications
    recent = con.execute("""
        SELECT j.company, j.title, a.applied_at, a.method
        FROM applications a
        JOIN jobs j ON a.job_id = j.id
        ORDER BY a.applied_at DESC
        LIMIT 5
    """).fetchall()
    
    # Count pending jobs
    pending = con.execute("""
        SELECT COUNT(*) FROM jobs 
        WHERE status = 'tailored' AND fit_score >= 75
    """).fetchone()[0]
    
    con.close()
    
    print("=" * 70)
    print("  AUTO-APPLY STATUS CHECK")
    print("=" * 70)
    print(f"  Applied Today:  {today_count}")
    print(f"  Pending Jobs:   {pending}")
    print("-" * 70)
    
    if recent:
        print("  LATEST APPLICATIONS:")
        for app in recent:
            time_str = datetime.fromisoformat(app['applied_at']).strftime('%H:%M')
            print(f"    [{time_str}] {app['company'][:25]:<25} - {app['title'][:30]}")
    
    print("=" * 70)
    
except Exception as e:
    print(f"Status check error: {e}")
