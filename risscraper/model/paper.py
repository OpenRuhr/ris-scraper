# encoding: utf-8

"""
Copyright (c) 2012 Marian Steinbach

Hiermit wird unentgeltlich jeder Person, die eine Kopie der Software und
der zugehörigen Dokumentationen (die "Software") erhält, die Erlaubnis
erteilt, sie uneingeschränkt zu benutzen, inklusive und ohne Ausnahme, dem
Recht, sie zu verwenden, kopieren, ändern, fusionieren, verlegen
verbreiten, unterlizenzieren und/oder zu verkaufen, und Personen, die diese
Software erhalten, diese Rechte zu geben, unter den folgenden Bedingungen:

Der obige Urheberrechtsvermerk und dieser Erlaubnisvermerk sind in allen
Kopien oder Teilkopien der Software beizulegen.

Die Software wird ohne jede ausdrückliche oder implizierte Garantie
bereitgestellt, einschließlich der Garantie zur Benutzung für den
vorgesehenen oder einen bestimmten Zweck sowie jeglicher Rechtsverletzung,
jedoch nicht darauf beschränkt. In keinem Fall sind die Autoren oder
Copyrightinhaber für jeglichen Schaden oder sonstige Ansprüche haftbar zu
machen, ob infolge der Erfüllung eines Vertrages, eines Delikts oder anders
im Zusammenhang mit der Software oder sonstiger Verwendung der Software
entstanden.
"""

from base import Base
import filters


class Paper(Base):
  """
  A paper class
  """
  def __init__(self, identifier=None, numeric_id=None, reference_number=None, title=None, type=None, date=None, original_url=None,
      paper=None, document=None):
    self.identifier = identifier
    self.numeric_id = numeric_id
    self.reference_number = reference_number
    self.x_title = title
    self.type = type
    self.x_date = date
    self.original_url = original_url
    # Relations
    self.document = document
    self.paper = paper
    super(Paper, self).__init__()

  @property
  def date(self):
    """Fancy getter for the date property"""
    return self.x_date

  @date.setter
  def date(self, value):
    """
    Fancy setter for the x_date property, which
    applies a string-to-datetime filter if necessary
    """
    if type(value) == str:
      self.x_date = filters.datestring_to_datetime(value)
    else:
      self.x_date = value

  @property
  def title(self):
    return self.x_title

  @title.setter
  def title(self, value):
    self.x_title = value.strip()
