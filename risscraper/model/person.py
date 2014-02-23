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


class Person(Base):
  """
  A committee class
  """
  def __init__(self, identifier=None, numeric_id=None, title=None, sex=None,
      address=None, house_number=None, postalcode=None, city=None, phone=None, fax=None, mobile=None, email=None, website=None,
      firstname=None, lastname=None, original_url=None, last_modified=None, committee=None):
    self.identifier = identifier
    self.numeric_id = numeric_id
    self.title = title
    self.sex = sex
    self.firstname = firstname
    self.lastname = lastname
    self.address = address
    self.postalcode = postalcode
    self.city = city
    self.phone = phone
    self.fax = fax
    self.mobile = mobile
    self.original_url = original_url
    self.last_modified = last_modified
    self.x_committee = committee
    super(Person, self).__init__()


  @property
  def committee(self):
    """Fancy getter for the x_date_start property"""
    return self.x_committee

  @committee.setter
  def committee(self, value):
    """
    Fancy setter for the x_start property, which
    applies a string-to-datetime filter if ecessary
    """
    for i in range(len(value)):
      if 'start' in value[i]:
        if type(value[i]['start']) == str:
          value[i]['start'] = filters.datestring_to_datetime(value[i]['start'])
      if 'start' in value[i]:
        if type(value[i]['start']) == str:
          value[i]['start'] = filters.datestring_to_datetime(value[i]['start'])
    self.x_committee = value
