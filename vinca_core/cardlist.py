from vinca_core.card import Card
from vinca_core import julianday
from re import fullmatch
import datetime
import json

from functools import partialmethod

class Cardlist(list):
        """"""
        ''' A Cardlist is basically just an SQL query linked to a database
        The filter, sort, findall, and slice methods build up this query
        When used as an iterator it is just a list of cards (ids) 
        It is responsible for knowing its database, usually ~/cards.db '''

        def __init__(self, cursor, conditions=['visibility != "purged"'],
                           ORDER_BY = (" ORDER BY max(last_edit_date, last_review_date) DESC"), 
                           deck = None,
            ):
                self._cursor = cursor   
                self._conditions = conditions
                self._ORDER_BY = ORDER_BY
                self.deck = deck or 'cards';
                self.filters = {};
                # we intentionally skip calling super().__init__ because we only are calling ourselves a list
                # so that Fire thinks we are one. We don't actually care about inheritance!

        def _copy(self):
                # create a copy of the conditions list obejct (lists are mutable!)
                # we don't want to be affected by subsequent changes to conditions
                return self.__class__(
                        self._cursor,
                        self._conditions.copy(),
                        self._ORDER_BY)

        @property
        def _SELECT_IDS(self):
                """SQL Query of all card IDs. Check this first when debugging."""
                return f'SELECT id FROM {self.deck}' + self._WHERE + self._ORDER_BY

        @property
        def _WHERE(self):
                return ' WHERE ' + ' AND '.join(self._conditions)

        @property
        def make_deck(self, name):
                assert name != cards
                self._cursor.execute(f'CREATE VIEW {name} AS'
                                     f'SELECT * FROM {self.deck}' + self._WHERE)
                self._cursor.execute(f'INSERT INTO decks (name, json)'
                                     f'VALUES (?, ?)', (name, json.dumps(self.filters)) )
                self._cursor.connection.commit()


        def drop(self):
                assert self.deck != 'cards'
                self._cursor.execute(f'DROP VIEW {self.deck}')
                self._cursor.execute(f'DELETE FROM decks WHERE name = {self.deck}')
                self._cursor.connection.commit()

        def explicit_cards_list(self, LIMIT = 1000):
                self._cursor.execute(self._SELECT_IDS + f' LIMIT {LIMIT}')
                ids = [row[0] for row in self._cursor.fetchall()]
                return [Card(id, self._cursor) for id in ids]

        def __getitem__(self, arg):
                # access cards by their index
                # we use human-oriented indexing beginning with 1...
                if type(arg) is slice:
                        idx = arg.stop 
                elif type(arg) is int:
                        idx = arg
                else:
                        raise ValueError
                self._cursor.execute(self._SELECT_IDS + f' LIMIT 1 OFFSET {idx - 1}')
                card_id = self._cursor.fetchone()[0]
                return Card(card_id, self._cursor)

        def __bool__(self):
                return len(self) > 0

        def __len__(self):
                self._cursor.execute(f'SELECT COUNT(*) FROM {self.deck} ' + self._WHERE)
                return self._cursor.fetchone()[0]

        def tags(self):
                """all tags in this cardlist """
                self._cursor.execute(f'SELECT tag FROM tags JOIN '
                    f'({self._SELECT_IDS}) ON tags.card_id=id GROUP BY tag')
                return [row[0] for row in self._cursor.fetchall()]

        def filter(self, *,
                   search = None,
                   require_parameters = True,
                   tag = None, tags_yes = None, tags_no = None,
                   created_after=None, created_before=None,
                   due_after=None, due_before=None,
                   deleted=None, due=None, new=None, card_type=None,
                   images=None, audio=None,
                   invert=False):
                self.filters.update(locals())
                """filter the collection"""
                # The default values of None signify that we will not filter
                # by this predicate. For example, new=False means that we will
                # only show cards which are not new, but new=None means that
                # we will show all cards.
                NOW = julianday.now() # date as a float e.g. 16300.4 days since unix epoch
                TODAY = int(NOW)

                # preprocess dates
                cleaned_dates = {'created_after': created_after,
                                'created_before': created_before,
                                     'due_after': due_after,
                                    'due_before': due_before,}
                # cast dates to myformat: number of days since epoch
                for key, value in cleaned_dates.items():
                    if value is None or value=='':
                        continue
                    elif type(value) is int:
                        # a number like +7 specifies a date relative to today
                        cleaned_dates[key] = TODAY + value
                    elif type(value) is str and fullmatch('[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
                        # check for iso date format e.g. 1999-06-14
                        date       = datetime.date.fromisoformat(value)
                        epoch_date = datetime.date.fromisoformat('1970-01-01')
                        elapsed_days = (date - epoch_date).days
                        cleaned_dates[key] = elapsed_days
                    else:
                        raise ValueError(f'parameter {key} received unparseable value of {value}')
                # process tags lists into strings
                tags_yes_string = ', '.join([ f'"{tag}"' for tag in (tags_yes or []) ])
                tags_no_string  = ', '.join([ f'"{tag}"' for tag in (tags_no or []) ])

                parameters_conditions = (
                        # search
                        (search, f"(front_text LIKE '%{search}%' OR back_text LIKE '%{search}%')"),
                        # tag
                        # the count(1) gives 1 if the record exists else 0
                        (tag, f"(SELECT count(1) FROM tags WHERE card_id=cards.id AND tag='{tag}')"),
                        (tags_yes, f"(SELECT count(1) FROM tags WHERE card_id=cards.id AND tag in ({tags_yes_string}) )"),
                        (tags_no,  f"(SELECT count(1) FROM tags WHERE card_id=cards.id AND NOT tag in ({tags_no_string}) )"),
                        # date conditions
                        (cleaned_dates['created_after'],  f"create_date > {cleaned_dates['created_after']}"),
                        (cleaned_dates['created_before'], f"create_date < {cleaned_dates['created_before']}"),
                        (cleaned_dates['due_after'],      f"due_date    > {cleaned_dates['due_after']}"),
                        (cleaned_dates['due_before'],     f"due_date    < {cleaned_dates['due_before']}"),
                        # boolean conditions
                        (due, f"due_date < {NOW}"),
                        (deleted, f"visibility = 'deleted'"),
                        (card_type, f'''card_type = "{card_type}"'''),
                        (new, f"due_date = create_date"),
                        (images, "(front_image_id IS NOT NULL OR back_image_id IS NOT NULL)"),
                        (audio, "(front_audio_id IS NOT NULL OR back_audio_id IS NOT NULL)"),
                )

                # assert that at least one filter predicate has been specified
                if require_parameters and all([p is None for p,c in parameters_conditions]):
                        return '''Examples:
filter --due                    ` due cards                  
filter --due-before -7            overdue by more than a week
filter --contains-images          cards containing images                           
filter --tag TAG --invert         cards not containing TAG   

Read `filter --help` for a complete list of predicates'''

                new_cardlist = self._copy()
                for parameter, condition in parameters_conditions:
                        if parameter is not None and parameter!='any' and parameter != '':
                                n = 'NOT ' if invert ^ (parameter is False) else ''
                                new_cardlist._conditions.append(n + condition)
                return new_cardlist

        def sort(self, criterion=None, *, reverse=False):
                crit_dict = {'overdue': ' ORDER BY due_date',
                             'old': ' ORDER BY create_date',
                             'random': ' ORDER BY RANDOM()',
                             'time': ' ORDER BY (edit_seconds + review_seconds)',
                             'total time': ' ORDER BY (edit_seconds + review_seconds)',
                             'recent': ' ORDER BY max(last_review_date, last_edit_date)',
                              }
                if criterion not in crit_dict:
                        return f'supply a criterion: {" | ".join(crit_dict.keys())}'
                new_cardlist = self._copy()
                new_cardlist._ORDER_BY = crit_dict[criterion]
                # Sometimes it is natural to see the highest value first by default
                reverse ^= criterion in ('recent', 'time', 'total time')
                direction = ' DESC' if reverse else ' ASC'
                new_cardlist._ORDER_BY += direction
                return new_cardlist

        def _change_visibility(self, visibility, date = None):
                assert visibility in ('visible','deleted','purged')
                date = date or float(julianday.now())
                self._cursor.execute('INSERT INTO edits (card_id, visibility, date) '
                                     f'SELECT id, "{visibility}", {date} FROM {self.deck} '
                                     f'{self._WHERE} AND visibility != "{visibility}"') 
                self._cursor.connection.commit()
                return self._cursor.rowcount
        _delete = partialmethod(_change_visibility, 'deleted')
        _restore = partialmethod(_change_visibility, 'visible')
        _purge = partialmethod(_change_visibility, 'purged')

        def _postpone(self, n, date):
                date = date or float(julianday.now())
                self._cursor.execute('INSERT INTO edits (card_id, due_date, date) '
                                     f'SELECT id, (due_date + {n}), {date} FROM {self.deck} ' + self._WHERE)
                self._cursor.connection.commit()
                return self._cursor.rowcount

        def tag(self, tag):
                self._cursor.execute(f'INSERT INTO tag_edits (card_id, tag) '
                                     f'SELECT id, "{tag}" FROM {self.deck} ' + self._WHERE)
                self._cursor.connection.commit()
                return self._cursor.rowcount

        def remove_tag(self, tag):
                self._cursor.execute(f'INSERT INTO tag_edits (card_id, tag, active) '
                                     f'SELECT id, "{tag}", 0 FROM {self.deck} ' + self._WHERE)
                self._cursor.connection.commit()
                return self._cursor.rowcount
