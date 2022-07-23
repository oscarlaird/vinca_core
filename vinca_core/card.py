'''
Core functionality of a Vinca Card

Some of this code implements a rudimentary ORM
The __getitem__ and __setitem__ methods read and write SQLite on the fly.

Methods which interface with the database:
- _update (create an edit record changing the card's properties)
- _log    (create a review record)

Besides interfacing with the database:
- history        (returns an array containing the history of the card)
- hypo_due_dates (tells us what the due_date would be if we pressed good)
- _schedule      (schedule the card based on its review history)

'''

from vinca_core.julianday import JulianDate, today
from vinca_core.scheduling import Review, History

from functools import partialmethod

class Card:
    # A card is a dictionary
    # its data is loaded from SQL on the fly and saved to SQL on the fly

    _misc_fields = ('card_type','visibility')
    _date_fields = ('create_date', 'due_date','last_edit_date','last_review_date')  # float valued
    _text_fields = ('front_text', 'back_text','extra','hint','source','spelltest')
    _media_id_fields = ('front_image_id', 'back_image_id', 'front_audio_id', 'back_audio_id', 'diagram_id','diagram_data_id')
    _time_fields = ('edit_seconds','review_seconds','total_seconds')

    _id_fields = ('id',) + _media_id_fields # int valued
    _int_fields = _id_fields + _time_fields
    _str_fields = _misc_fields + _text_fields  # str valued
    _concrete_fields = _date_fields + _int_fields + _str_fields

    _virtual_media_fields = ('front_image','back_image','front_audio','back_audio','diagram','diagram_data')
    _fields = _concrete_fields + _virtual_media_fields

    _editable_fields =  ('front_image_id','back_image_id','front_audio_id','back_audio_id','diagram_id','diagram_data_id',
                         'front_text','back_text','source','extra','hint','spelltest',
                         'card_type','visibility','due_date')

    def __init__(self, card_id, cursor):
        self._dict = dict(id=int(card_id))
        self._cursor = cursor

    def _exists(self):
        return bool(self._cursor.execute('SELECT COUNT(1) FROM cards WHERE id = ?',(self.id,)).fetchone()[0])
    __bool__ = _exists

    # commit to SQL any variables that are changed (by editing, deleting, scheduling, etc.)
    def __setitem__(self, key, value):
        assert key != 'id', 'Card Id cannot be changed!'
        assert key in self._fields
        self._dict[key] = value
        # commit change to card-dictionary to SQL database
        if key in self._virtual_media_fields:
            self._set_virtual_media_field(key, value)
        else:
            self._cursor.execute(f'INSERT INTO edits (card_id, {key}) VALUES (?, ?)',(self.id, value))
            self._cursor.connection.commit()
    __setattr__ = __setitem__ # easy dot notation

    def _set_virtual_media_field(self, key, value):
            media_id = self._upload_media(self._cursor, content=value)
            field = key + '_id' # front_image refers to the field "front_image_id"
            self._cursor.execute(f'INSERT INTO edits (card_id, {field}) VALUES (?, ?)', (self.id, media_id))
            self._cursor.connection.commit()

    @staticmethod
    def _upload_media(cursor, content, id=None):
            # check if it already exists
            cursor.execute('SELECT id FROM media WHERE content = ?',(content,))
            if result := cursor.fetchone():
                # return id of already existing media
                return result[0]
            cursor.execute('INSERT INTO media (content) VALUES (?);',(content,))
            cursor.execute('SELECT id FROM media WHERE rowid = last_insert_rowid()')
            cursor.connection.commit();
            media_id = cursor.fetchone()[0]
            return media_id

    @staticmethod
    def _get_media(cursor, media_id):
        result = cursor.execute('SELECT content FROM media WHERE id = ?', (media_id,)).fetchone()
        if not result:
            return None
        return result[0]


    def _update(self, d, date=None, seconds=0):
        # N.B: The updated card is not requested.
        assert type(d) is dict or type(d) is Card
        assert all([k in self._editable_fields for k in d]), f'Bad Key. Can only update keys: {self._editable_fields}'
        if not d.keys():
            return
        if date: # override the database's default timestamping
            d['date'] = date
        if seconds:  # specify how long it took to edit the card
            d['seconds'] = seconds
        d['card_id'] = self.id
        self._dict.update(d)
        keys = ','.join(d.keys()) 
        question_marks = ','.join('?'*len(d.keys()))
        self._cursor.execute(f'INSERT INTO edits ({keys}) VALUES ({question_marks})',list(d.values()))
        self._cursor.connection.commit()

    # load attributes from SQL on the fly
    # and put them in self._dict for future reference
    def __getitem__(self, key):
        if key not in self._fields:
            raise KeyError(f'Field "{key}" does not exist')
        if key not in self._dict.keys():
            # load attribute from the database if we haven't yet
            # for the special virtual field front_image
            # we have to look up the content in the media table based on front_image_id
            if key in self._virtual_media_fields:
                value = self._get_virtual_media_field(key)
            # other keys we can query from the cards table directly
            else:
                value = self._cursor.execute(f'SELECT {key} FROM cards'
                                             ' WHERE id = ?', (self.id,)).fetchone()[0]
            # preprocess certain values to cast them to better types:
            # A JulianDate is just a wrapper class for floats
            # which prints out as a date
            if key in self._date_fields:
                value = JulianDate(value)
            self._dict[key] = value
        return self._dict[key]
    __getattr__ = __getitem__

    def _get_virtual_media_field(self, key):
        # if we query for "front_image" we need to access the database field front_image_id. So:
        key_id = key + '_id' # change front_image to front_image_id
        media_id = self._cursor.execute(f'SELECT {key_id} FROM cards WHERE id = ?',(self.id,)).fetchone()[0]
        value = None if not media_id else self._cursor.execute(f'SELECT content FROM media '
                                            'WHERE id = ?', (media_id,)).fetchone()[0]


    def _log_review(self, grade, seconds, new_due_date, date = None):
        log = {'card_id':self.id, 'seconds': seconds, 'grade':grade, 'new_due_date': new_due_date}
        if date: log['date'] = date
        field_names    = ','.join(log)            # card_id, seconds, grade
        question_marks = ','.join('?' * len(log)) # ?,?,?
        self._cursor.execute(f'INSERT INTO reviews ({field_names}) VALUES ({question_marks})', tuple(log.values()))
        self._cursor.connection.commit()

    @property
    def history(self):
        self._cursor.execute('SELECT date, grade, seconds FROM reviews WHERE card_id = ?',(self.id,))
        reviews = [Review(*row) for row in self._cursor.fetchall()]
        return History(reviews, create_date = self.create_date)

    def _schedule(self):
        self.due_date = self.history.new_due_date
        return self.due_date

    @classmethod
    def _new_card(cls, cursor):
        cursor.execute("INSERT INTO edits DEFAULT VALUES")
        cursor.connection.commit()
        id = cursor.execute("SELECT card_id FROM edits WHERE"
                            " rowid = last_insert_rowid()").fetchone()[0]
        return cls(id, cursor)

    @property
    def is_due(self):
        return self.due_date <= today()

    def remove_tag(self, tag):
        self._cursor.execute('INSERT INTO tag_edits (card_id, tag, active) VALUES (?, ?, ?)', (self.id, tag, 0))
        self._cursor.connection.commit()

    def tags(self):
        self._cursor.execute('SELECT tag FROM tags WHERE card_id = ?',(self.id,))
        return [row[0] for row in self._cursor.fetchall()]

    def add_tag(self, tag):
        self._cursor.execute('INSERT INTO tag_edits (card_id, tag) VALUES (?, ?)', (self.id, tag))
        self._cursor.connection.commit()

    def _change_visibility(self, visibility, date = None):
        assert visibility in ('deleted','visible','purged')
        date = date or julianday.now()
        self._cursor.execute('INSERT INTO edits (card_id, visibility, date) VALUES (?, ?, ?)',(self.id, visibility, date))
        self._cursor.connection.commit()
    _delete = partialmethod(_change_visibility, 'deleted')
    _restore = partialmethod(_change_visibility, 'visible')
    _purge = partialmethod(_change_visibility, 'purged')




