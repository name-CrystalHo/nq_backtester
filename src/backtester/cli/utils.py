"""
Utility functions for CLI operations.

Provides common functionality for file handling, formatting, and user interaction.
"""

import click
import os
from pathlib import Path
from typing import Optional
from contextlib import contextmanager
try:
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.console import Console
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


def validate_file_exists(file_path: Path, file_type: str = "File") -> bool:
    """
    Validate that a file exists and is readable.
    
    Args:
        file_path: Path to the file to validate
        file_type: Type description for error messages
        
    Returns:
        True if file exists and is readable, False otherwise
    """
    if not file_path.exists():
        print_error(f"{file_type} not found: {file_path}")
        return False
    
    if not file_path.is_file():
        print_error(f"Path is not a file: {file_path}")
        return False
    
    try:
        # Test if file is readable
        with open(file_path, 'r') as f:
            f.read(1)
        return True
    except PermissionError:
        print_error(f"Permission denied reading file: {file_path}")
        return False
    except Exception as e:
        print_error(f"Error accessing file {file_path}: {e}")
        return False


def format_file_size(size_mb: float) -> str:
    """
    Format file size in human-readable format.
    
    Args:
        size_mb: Size in megabytes
        
    Returns:
        Formatted size string
    """
    if size_mb < 1:
        return f"{size_mb * 1024:.1f} KB"
    elif size_mb < 1024:
        return f"{size_mb:.1f} MB"
    else:
        return f"{size_mb / 1024:.1f} GB"


def format_duration(seconds: float) -> str:
    """
    Format duration in human-readable format.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted duration string
    """
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    elif seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        remaining_seconds = seconds % 60
        return f"{minutes}m {remaining_seconds:.1f}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


def print_success(message: str):
    """Print success message in green."""
    if RICH_AVAILABLE:
        console = Console()
        console.print(message, style="green")
    else:
        click.echo(click.style(message, fg='green'))


def print_error(message: str):
    """Print error message in red."""
    if RICH_AVAILABLE:
        console = Console(stderr=True)
        console.print(message, style="red")
    else:
        click.echo(click.style(message, fg='red'), err=True)


def print_info(message: str):
    """Print info message in blue."""
    if RICH_AVAILABLE:
        console = Console()
        console.print(message, style="blue")
    else:
        click.echo(click.style(message, fg='blue'))


def print_warning(message: str):
    """Print warning message in yellow."""
    if RICH_AVAILABLE:
        console = Console()
        console.print(message, style="yellow")
    else:
        click.echo(click.style(message, fg='yellow'))


@contextmanager
def create_progress_bar(description: str):
    """
    Create a progress bar context manager.
    
    Args:
        description: Description for the progress bar
        
    Yields:
        Progress bar instance
    """
    if RICH_AVAILABLE:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=Console()
        ) as progress:
            yield progress
    else:
        # Fallback for when rich is not available
        class SimpleProgress:
            def add_task(self, description, total=None):
                click.echo(f"Starting: {description}")
                return 0
            
            def update(self, task_id, completed=None, total=None):
                if completed == total and total is not None:
                    click.echo("✅ Completed!")
            
            def advance(self, task_id):
                pass
        
        yield SimpleProgress()


def confirm_operation(message: str, default: bool = False) -> bool:
    """
    Ask user for confirmation.
    
    Args:
        message: Confirmation message
        default: Default response if user just presses Enter
        
    Returns:
        True if user confirmed, False otherwise
    """
    return click.confirm(message, default=default)


def get_file_info(file_path: Path) -> dict:
    """
    Get basic information about a file.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Dictionary with file information
    """
    try:
        stat = file_path.stat()
        return {
            'size_bytes': stat.st_size,
            'size_mb': stat.st_size / (1024 * 1024),
            'modified': stat.st_mtime,
            'readable': file_path.is_file() and os.access(file_path, os.R_OK)
        }
    except Exception:
        return {
            'size_bytes': 0,
            'size_mb': 0,
            'modified': 0,
            'readable': False
        }


def truncate_path(path: Path, max_length: int = 50) -> str:
    """
    Truncate path for display purposes.
    
    Args:
        path: Path to truncate
        max_length: Maximum length of displayed path
        
    Returns:
        Truncated path string
    """
    path_str = str(path)
    if len(path_str) <= max_length:
        return path_str
    
    # Try to keep filename and some parent directory
    filename = path.name
    if len(filename) >= max_length - 3:
        return f"...{filename[-(max_length-3):]}"
    
    # Calculate how much of the parent path we can keep
    remaining = max_length - len(filename) - 3 - 1  # 3 for "...", 1 for separator
    parent_str = str(path.parent)
    
    if remaining <= 0:
        return f"...{filename}"
    
    if len(parent_str) <= remaining:
        return path_str
    
    truncated_parent = parent_str[-remaining:]
    result = f"...{truncated_parent}\\{filename}"
    
    # Ensure result doesn't exceed max_length
    if len(result) > max_length:
        excess = len(result) - max_length
        truncated_parent = truncated_parent[excess:]
        result = f"...{truncated_parent}\\{filename}"
    
    return result