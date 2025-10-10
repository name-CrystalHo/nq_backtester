#!/usr/bin/env python3
"""
Configure Git and create initial commit
"""

import subprocess
import sys
from pathlib import Path

# Git executable path
GIT_PATH = r"C:\Program Files\Git\bin\git.exe"

def run_git_command(command, description):
    """Run a git command and handle errors."""
    full_command = f'"{GIT_PATH}" {command}'
    print(f"📋 {description}...")
    try:
        result = subprocess.run(full_command, shell=True, capture_output=True, text=True, cwd=".")
        if result.returncode == 0:
            print(f"✅ {description} - Success")
            if result.stdout.strip():
                print(f"   {result.stdout.strip()}")
            return True
        else:
            print(f"❌ {description} - Failed")
            if result.stderr.strip():
                print(f"   Error: {result.stderr.strip()}")
            return False
    except Exception as e:
        print(f"💥 {description} - Exception: {e}")
        return False

def setup_git_config():
    """Set up Git configuration and create initial commit."""
    
    print("🚀 Setting up Git repository for NQ Backtester")
    print("=" * 50)
    
    # Get user information
    print("\n⚙️  Git Configuration Setup")
    name = input("📝 Enter your name for Git commits: ").strip()
    if not name:
        print("❌ Name is required!")
        return False
    
    email = input("📧 Enter your email for Git commits: ").strip()
    if not email:
        print("❌ Email is required!")
        return False
    
    # Set user configuration
    if not run_git_command(f'config user.name "{name}"', "Setting Git user name"):
        return False
    
    if not run_git_command(f'config user.email "{email}"', "Setting Git user email"):
        return False
    
    # Update README
    print("\n📝 Updating README...")
    readme_new = Path("README_NEW.md")
    readme_old = Path("README.md")
    
    if readme_new.exists():
        # Replace USERNAME placeholder with actual username
        content = readme_new.read_text(encoding='utf-8')
        username = input("📝 Enter your GitHub username (or press Enter to use placeholder): ").strip()
        if username:
            content = content.replace("USERNAME", username)
            readme_new.write_text(content, encoding='utf-8')
        
        # Replace old README
        if readme_old.exists():
            readme_old.unlink()
        readme_new.rename(readme_old)
        print("✅ README updated")
    
    # Stage all files
    if not run_git_command("add .", "Staging all files"):
        return False
    
    # Create initial commit
    commit_message = "Initial commit: NQ Backtester with Polars integration"
    if not run_git_command(f'commit -m "{commit_message}"', "Creating initial commit"):
        return False
    
    # Show status
    run_git_command("status", "Checking repository status")
    
    # Show file count
    run_git_command("ls-files | wc -l", "Counting tracked files")
    
    print(f"\n🎉 Git repository successfully created!")
    print(f"\n📋 Next Steps:")
    print(f"   1. Create a GitHub repository at: https://github.com/new")
    print(f"      - Repository name: nq_backtester")
    print(f"      - Description: High-performance Python tick data backtester")
    print(f"      - DON'T initialize with README (we have one)")
    print(f"   2. Add remote origin:")
    if username:
        print(f'      git remote add origin https://github.com/{username}/nq_backtester.git')
    else:
        print(f'      git remote add origin https://github.com/YOUR_USERNAME/nq_backtester.git')
    print(f"   3. Push to GitHub:")
    print(f'      git push -u origin main')
    
    print(f"\n💡 Pro Tip: Add these topics to your GitHub repo:")
    print(f"   backtesting, trading, polars, python, ninjatrader, financial-data")
    
    return True

if __name__ == "__main__":
    success = setup_git_config()
    if not success:
        sys.exit(1)