from datetime import datetime, timezone, timedelta
utc = datetime.now(timezone.utc)
ist = utc + timedelta(hours=5, minutes=30)
print('UTC:', utc.strftime('%H:%M:%S'))
print('IST:', ist.strftime('%H:%M:%S'))
print('Your system time:', datetime.now().strftime('%H:%M:%S'))
