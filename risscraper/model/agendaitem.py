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


class Agendaitem(Base):
  """
  A agendaitem class
  """
  def __init__(self, identifier=None, numeric_id=None, sequence_number = None, public=None,
      title=None, result=None, result_details=None, resolution_text=None, original_url=None,
      meeting=None, paper=None):
    self.identifier = identifier
    self.numeric_id = numeric_id
    self.sequence_number = sequence_number
    self.public = public
    self.title = title
    self.result = result
    self.result_details = result_details
    self.resolution_text = resolution_text
    self.original_url = original_url
    # Relations
    self.meeting = meeting
    self.paper = paper
    super(Agendaitem, self).__init__()
