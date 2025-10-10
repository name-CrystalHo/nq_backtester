# Git Repository Setup Instructions

## 📥 Step 1: Install Git

1. **Download Git for Windows**: https://git-scm.com/download/windows
2. **Run the installer** with these recommended settings:
   - ✅ Use Visual Studio Code as Git's default editor (if you have VS Code)
   - ✅ Let Git decide the default branch name (will use 'main')
   - ✅ Git from the command line and also from 3rd-party software
   - ✅ Use bundled OpenSSH
   - ✅ Use the OpenSSL library
   - ✅ Checkout Windows-style, commit Unix-style line endings
   - ✅ Use Windows' default console window
   - ✅ Default (fast-forward or merge)
   - ✅ Git Credential Manager Core
   - ✅ Enable file system caching
3. **Restart PowerShell/VS Code** after installation

## 🚀 Step 2: Initialize Repository

After installing Git, run these commands in your project directory:

```bash
# Initialize repository
git init

# Configure Git (first time only)
git config user.name "Your Name"
git config user.email "your.email@example.com"

# Set default branch to main
git config init.defaultBranch main

# Add all files
git add .

# Create initial commit
git commit -m "Initial commit: NQ Backtester with Polars integration"

# Check status
git status
```

## 🌐 Step 3: Create GitHub Repository

1. **Go to GitHub**: https://github.com/new
2. **Repository name**: `nq_backtester`
3. **Description**: `High-performance Python tick data backtester with Polars integration`
4. **Visibility**: Choose Public or Private
5. **DON'T** initialize with README, .gitignore, or license (we already have them)
6. **Click "Create repository"**

## 🔗 Step 4: Connect to GitHub

After creating the GitHub repository, run:

```bash
# Add remote origin (replace USERNAME with your GitHub username)
git remote add origin https://github.com/USERNAME/nq_backtester.git

# Push to GitHub
git push -u origin main
```

## 📋 Step 5: Update README

1. Replace `USERNAME` in `README_NEW.md` with your actual GitHub username
2. Replace the current README:

```bash
# Replace old README with new one
mv README_NEW.md README.md
git add README.md
git commit -m "Update README with badges and better documentation"
git push
```

## 🎯 Quick Setup Script

Or simply run the setup script after installing Git:

```bash
python setup_git.py
```

## ✅ Verification

After setup, verify everything works:

```bash
# Check Git status
git status

# Check remote
git remote -v

# Check recent commits
git log --oneline -5
```

## 🚀 Next Steps

1. **Enable GitHub Actions**: The CI/CD pipeline will automatically run tests
2. **Add Collaborators**: If working with others
3. **Create Issues**: For tracking features and bugs
4. **Setup Branch Protection**: For the main branch
5. **Add Topics**: Tag your repo with relevant topics like `backtesting`, `trading`, `polars`, `python`

## 📊 Repository Statistics

Once set up, your repository will include:
- ✅ **40+ source files** with clean, production-ready code
- ✅ **8.66 GB processed data** (gitignored, stored locally)
- ✅ **Comprehensive test suite** with CI/CD
- ✅ **Professional documentation** with badges and guides
- ✅ **Automated workflows** for testing and quality checks