"""
bot_detector.py - Scores Instagram accounts for bot likelihood
"""

import re


def score_account(user_info) -> dict:
    """
    Returns a score dict. Higher score = more likely a bot.
    Remove if score >= config['min_score'] (default: 3)
    """
    flags = {}

    # Strong signals (worth 1 point each)
    flags["no_profile_pic"]   = not bool(user_info.profile_pic_url)
    flags["zero_posts"]       = user_info.media_count == 0
    flags["private_no_posts"] = user_info.is_private and user_info.media_count == 0

    # Medium signals
    flags["no_bio"]           = not bool(user_info.biography)
    flags["very_new_account"] = (
        user_info.media_count < 3 and
        user_info.follower_count < 10
    )

    # Ratio signals
    following = user_info.following_count or 1
    follower  = user_info.follower_count or 0
    flags["follow_bomb"]  = following > 3000 and follower < 100
    flags["mass_follower"] = following > 7500  # near Instagram's limit

    # Username pattern signals
    username = user_info.username
    flags["numeric_suffix"] = bool(re.search(r'\d{4,}$', username))
    flags["random_chars"]   = bool(re.search(r'[a-z]{2}\d{3}[a-z]{2}', username))

    score = sum(flags.values())

    return {
        "score":    score,
        "flags":    flags,
        "username": username,
    }