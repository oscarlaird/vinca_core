import datetime

def unixepoch_local():
        return (datetime.datetime.now() - datetime.datetime(year=1970, month=1, day=1)).total_seconds()

def now():
        return unixepoch_local() / 86400

def today():
        today = int(now())
        assert today == (datetime.date.today() - datetime.date(year=1970,month=1,day=1)).days
        return today

class JulianDate(float):
        
        def __str__(self):
            date = datetime.date(year=1970,month=1,day=1) + datetime.timedelta(days = 1) * int(self)
            return str(date)

        @property
        def isoformat(self):
            return str(self)

        @property
        def relative_date(self):
            return int(self - today())
