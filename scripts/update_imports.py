#!/usr/bin/env python3
"""
Script to update all import statements from 'backtester.*' to 'src.backtester.*'
"""

import re
from pathlib import Path
import sys

def update_imports_in_file(file_path: Path) -> bool:
    """Update imports in a single file. Returns True if changes were made."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        original_content = content
        
        # Replace imports - careful to not replace imports that are already correct
        patterns = [
            # from src.backtester.xxx import yyy
            (r'\bfrom backtester\.', r'from src.backtester.'),
            # import src.backtester.xxx
            (r'\bimport backtester\.', r'import src.backtester.'),
            # import src.backtester (without dot)
            (r'\bimport backtester\b', r'import src.backtester'),
            # from src.backtester import xxx
            (r'\bfrom backtester import', r'from src.backtester import'),
        ]
        
        for old_pattern, new_pattern in patterns:
            content = re.sub(old_pattern, new_pattern, content)
        
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Updated: {file_path}")
            return True
        
        return False
        
    except Exception as e:
        print(f"Error updating {file_path}: {e}")
        return False

def main():
    """Update all Python files in the project."""
    root_dir = Path(__file__).parent.parent
    
    # Find all Python files
    patterns = ['**/*.py', '**/*.md']  # Include markdown for documentation
    files_to_update = []
    
    for pattern in patterns:
        files_to_update.extend(root_dir.glob(pattern))
    
    # Filter out files we don't want to modify
    exclude_patterns = [
        'scripts/update_imports.py',  # Don't modify this script
        '.git/',
        '__pycache__/',
        '.pytest_cache/',
        'venv/',
        'env/',
        '.benchmarks/'
    ]
    
    files_to_update = [
        f for f in files_to_update 
        if not any(exclude in str(f) for exclude in exclude_patterns)
    ]
    
    print(f"Found {len(files_to_update)} files to check...")
    
    updated_count = 0
    for file_path in files_to_update:
        if update_imports_in_file(file_path):
            updated_count += 1
    
    print(f"\nCompleted! Updated {updated_count} files.")

if __name__ == '__main__':
    main()