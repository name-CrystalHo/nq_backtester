from datetime import datetime
from zoneinfo import ZoneInfo

et_930 = datetime(2025, 6, 16, 9, 30, 0, tzinfo=ZoneInfo('America/New_York'))
utc_time = et_930.astimezone(ZoneInfo('UTC'))
print(f"9:30 AM ET on 6/16/2025 = {utc_time.strftime('%H:%M:%S')} UTC")
print(f"As naive datetime: {utc_time.replace(tzinfo=None)}")

# Also check 9:45 and 14:25
et_945 = datetime(2025, 6, 16, 9, 45, 0, tzinfo=ZoneInfo('America/New_York'))
print(f"9:45 AM ET = {et_945.astimezone(ZoneInfo('UTC')).strftime('%H:%M:%S')} UTC")

et_1425 = datetime(2025, 6, 16, 14, 25, 0, tzinfo=ZoneInfo('America/New_York'))
print(f"14:25 PM ET = {et_1425.astimezone(ZoneInfo('UTC')).strftime('%H:%M:%S')} UTC")
