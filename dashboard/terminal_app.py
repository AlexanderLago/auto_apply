# Terminal Dashboard for Auto-Apply Bot
# A simple TUI to manage and monitor job applications

import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
import config
from modules.tracker.models import Job, Application

# ── Database helpers ────────────────────────────────────────────────────────────

def get_db_connection():
    """Get a database connection with proper settings."""
    con = sqlite3.connect(config.DB_PATH, timeout=30.0)
    con.execute("PRAGMA busy_timeout=30000")
    con.row_factory = sqlite3.Row
    return con

def get_all_jobs():
    """Fetch all jobs with their application status."""
    con = get_db_connection()
    rows = con.execute("""
        SELECT j.*, 
               a.applied_at,
               a.method,
               a.notes,
               CASE WHEN a.id IS NOT NULL THEN 1 ELSE 0 END as applied
        FROM jobs j
        LEFT JOIN applications a ON j.id = a.job_id
        ORDER BY j.fit_score DESC, j.scraped_at DESC
    """).fetchall()
    con.close()
    return [dict(r) for r in rows]

def get_application_stats():
    """Get application statistics."""
    con = get_db_connection()
    
    # Total applications
    total = con.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
    
    # Applications today
    today = datetime.now().date().isoformat()
    today_count = con.execute("""
        SELECT COUNT(*) FROM applications 
        WHERE date(applied_at) = ?
    """, (today,)).fetchone()[0]
    
    # Success rate (submitted vs dry_run vs error)
    status_counts = con.execute("""
        SELECT status, COUNT(*) as count 
        FROM applications 
        GROUP BY status
    """).fetchall()
    
    # Applications by company
    company_counts = con.execute("""
        SELECT j.company, COUNT(a.id) as count
        FROM applications a
        JOIN jobs j ON a.job_id = j.id
        GROUP BY j.company
        ORDER BY count DESC
        LIMIT 10
    """).fetchall()
    
    con.close()
    
    status_dict = {r['status']: r['count'] for r in status_counts}
    submitted = status_dict.get('submitted', 0) + status_dict.get('dry_run', 0)
    errors = status_dict.get('error', 0)
    captcha = status_dict.get('captcha', 0)
    
    success_rate = (submitted / total * 100) if total > 0 else 0
    
    return {
        'total': total,
        'today': today_count,
        'submitted': submitted,
        'errors': errors,
        'captcha': captcha,
        'success_rate': success_rate,
        'by_company': [(r['company'], r['count']) for r in company_counts]
    }

def mark_job_applied(job_id, status='submitted', notes=''):
    """Mark a job as applied."""
    con = get_db_connection()
    try:
        con.execute("""
            INSERT INTO applications (job_id, resume_path, applied_at, method, notes)
            VALUES (?, '', ?, 'manual', ?)
        """, (job_id, datetime.now().isoformat(), notes))
        con.execute("UPDATE jobs SET status = 'applied' WHERE id = ?", (job_id,))
        con.commit()
        return True
    except Exception as e:
        con.rollback()
        return False
    finally:
        con.close()

def delete_job(job_id):
    """Delete a job from the queue."""
    con = get_db_connection()
    try:
        con.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
        con.commit()
        return True
    except Exception as e:
        con.rollback()
        return False
    finally:
        con.close()

def update_job_score(job_id, score):
    """Update a job's fit score."""
    con = get_db_connection()
    try:
        con.execute("UPDATE jobs SET fit_score = ? WHERE id = ?", (score, job_id))
        con.commit()
        return True
    except Exception as e:
        con.rollback()
        return False
    finally:
        con.close()

# ── Terminal UI helpers ─────────────────────────────────────────────────────────

def clear_screen():
    """Clear the terminal screen."""
    print('\033[2J\033[H', end='')

def print_header():
    """Print the dashboard header."""
    print("=" * 80)
    print("  AUTO-APPLY DASHBOARD")
    print("=" * 80)
    print(f"  Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)

def print_stats(stats):
    """Print application statistics."""
    print("\n  📊 APPLICATION STATISTICS")
    print("  " + "-" * 76)
    print(f"  | Total Applications:     {stats['total']:<5}  |  Today: {stats['today']:<5}  |  Success Rate: {stats['success_rate']:.1f}%  |")
    print("  " + "-" * 76)
    print(f"  | ✅ Submitted:  {stats['submitted']:<5}  |  ⚠️  Errors: {stats['errors']:<5}  |  🤖 Captcha: {stats['captcha']:<5}  |")
    print("  " + "-" * 76)
    
    if stats['by_company']:
        print("\n  🏢 TOP COMPANIES")
        print("  " + "-" * 76)
        for company, count in stats['by_company'][:5]:
            bar = "█" * min(count, 20)
            print(f"  | {company:<30} {bar} ({count})")
        print("  " + "-" * 76)

def print_job_list(jobs, selected_idx=0):
    """Print the job list with status indicators."""
    print("\n  💼 JOB QUEUE")
    print("  " + "-" * 76)
    print(f"  {'ID':<5} {'Status':<8} {'Score':<6} {'Company':<20} {'Title':<35}")
    print("  " + "-" * 76)
    
    for i, job in enumerate(jobs[:20]):  # Show top 20
        status_icon = "✅" if job['applied'] else "⏳"
        score = job['fit_score'] or 0
        
        # Highlight selected job
        if i == selected_idx:
            print(f"  \033[7m{job['id']:<5} {status_icon} {score:<6} {job['company'][:20]:<20} {job['title'][:35]:<35}\033[0m")
        else:
            print(f"  {job['id']:<5} {status_icon} {score:<6} {job['company'][:20]:<20} {job['title'][:35]:<35}")
    
    print("  " + "-" * 76)
    print(f"  Showing {min(len(jobs), 20)} of {len(jobs)} jobs")

def print_menu():
    """Print the action menu."""
    print("\n  📋 ACTIONS")
    print("  " + "-" * 76)
    print("  [1] Apply to selected job")
    print("  [2] Mark as applied (manual)")
    print("  [3] Remove from queue")
    print("  [4] Update fit score")
    print("  [5] Refresh data")
    print("  [Q] Quit")
    print("  " + "-" * 76)

def get_user_input(prompt=""):
    """Get user input."""
    try:
        return input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return 'q'

# ── Main dashboard loop ─────────────────────────────────────────────────────────

def dashboard():
    """Main dashboard loop."""
    selected_idx = 0
    
    while True:
        clear_screen()
        print_header()
        
        # Load data
        jobs = get_all_jobs()
        stats = get_application_stats()
        
        # Display
        print_stats(stats)
        print_job_list(jobs, selected_idx)
        print_menu()
        
        # Get user action
        action = get_user_input("\n  Enter action: ")
        
        if action == 'q':
            print("\n  Goodbye! 👋\n")
            break
        elif action == '1':
            # Apply to selected job
            if jobs and selected_idx < len(jobs):
                job = jobs[selected_idx]
                print(f"\n  Applying to {job['title']} at {job['company']}...")
                print("  (This will launch the browser - implement apply logic here)")
                input("  Press Enter to continue...")
        elif action == '2':
            # Mark as applied
            if jobs and selected_idx < len(jobs):
                job = jobs[selected_idx]
                if mark_job_applied(job['id'], 'submitted', 'Manual mark'):
                    print(f"\n  ✅ Marked {job['company']} - {job['title']} as applied")
                else:
                    print(f"\n  ❌ Failed to mark job as applied")
                input("  Press Enter to continue...")
        elif action == '3':
            # Remove from queue
            if jobs and selected_idx < len(jobs):
                job = jobs[selected_idx]
                confirm = get_user_input(f"  Remove {job['company']} - {job['title']}? (y/n): ")
                if confirm == 'y':
                    if delete_job(job['id']):
                        print(f"\n  🗑️  Job removed")
                    else:
                        print(f"\n  ❌ Failed to remove job")
                input("  Press Enter to continue...")
        elif action == '4':
            # Update fit score
            if jobs and selected_idx < len(jobs):
                job = jobs[selected_idx]
                new_score = get_user_input(f"  New fit score for {job['company']} (current: {job['fit_score']}): ")
                try:
                    score = float(new_score)
                    if update_job_score(job['id'], score):
                        print(f"\n  ✅ Score updated to {score}")
                    else:
                        print(f"\n  ❌ Failed to update score")
                except ValueError:
                    print("\n  ❌ Invalid score")
                input("  Press Enter to continue...")
        elif action == '5':
            # Refresh
            pass

if __name__ == '__main__':
    try:
        dashboard()
    except Exception as e:
        print(f"\n  ❌ Error: {e}\n")
        import traceback
        traceback.print_exc()
