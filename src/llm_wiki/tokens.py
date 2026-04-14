def count_tokens(text: str) -> int:
    """Estimate token count. Good enough for budgeting."""
    return len(text) // 4
