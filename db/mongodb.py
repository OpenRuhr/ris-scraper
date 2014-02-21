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

from pymongo import MongoClient
from pymongo import ASCENDING
from pymongo import DESCENDING
from bson.dbref import DBRef
import gridfs
import sys
from hashlib import md5
import logging
import re
import translitcodec
import pytz
import datetime


class MongoDatabase(object):
  """
  Database handler for a MongoDB backend
  """

  def __init__(self, config, options):
    client = MongoClient(config.DB_HOST, config.DB_PORT)
    self.db = client[config.DB_NAME]
    self.config = config
    self.options = options
    self.fs = gridfs.GridFS(self.db)
    self.slugify_re = re.compile(r'[\t !"#$%&\'()*\-/<=>?@\[\\\]^_`{|},.]+')

  def setup(self, config):
    """
    Initialize database, if not yet done. Shouln't destroy anything.
    """
    # body
    self.db.body.ensure_index([('rs', ASCENDING)], unique=True)
    #todo: put complete config in db
    self.body_uid = self.db.body.find_one({'rs': config.RS})
    if self.body_uid:
      self.body_uid = self.body_uid['_id']
    else:
      self.body_uid = self.db.body.insert({
        'rs': config.RS,
        'title': config.CITY
      })
    
    
    self.db.committee.ensure_index([('identifier', ASCENDING), ('body', ASCENDING)], unique=True)
    self.db.person.ensure_index([('identifier', ASCENDING), ('body', ASCENDING)], unique=True)
    self.db.organisation.ensure_index([('identifier', ASCENDING), ('body', ASCENDING)], unique=True)
    
    # meeting = session
    self.db.meeting.ensure_index([('identifier', ASCENDING), ('body', ASCENDING)], unique=True)
    self.db.meeting.ensure_index([('numeric_id', ASCENDING), ('body', ASCENDING)], unique=True)
    self.db.meeting.ensure_index([('slug', ASCENDING), ('body', ASCENDING)], unique=True)
    
    # agendaitem
    self.db.agendaitem.ensure_index([('identifier', ASCENDING), ('body', ASCENDING)], unique=True)
    self.db.agendaitem.ensure_index([('numeric_id', ASCENDING), ('body', ASCENDING)], unique=True)
    self.db.agendaitem.ensure_index([('slug', ASCENDING), ('body', ASCENDING)], unique=True)
    
    # paper = submission
    self.db.paper.ensure_index([('identifier', ASCENDING), ('body', ASCENDING)], unique=True)
    self.db.paper.ensure_index([('numeric_id', ASCENDING), ('body', ASCENDING)], unique=True)
    self.db.paper.ensure_index([('slug', ASCENDING), ('body', ASCENDING)], unique=True)
    
    # document = attachment
    self.db.document.ensure_index([('identifier', ASCENDING), ('body', ASCENDING)], unique=True)
    self.db.document.ensure_index([('slug', ASCENDING), ('body', ASCENDING)], unique=True)
    
    # committee
    self.db.committee.ensure_index([('identifier', ASCENDING), ('body', ASCENDING)], unique=True)
    # we don't have ids there, so its not unique
    self.db.committee.ensure_index([('numeric_id', ASCENDING), ('body', ASCENDING)], unique=False)
    self.db.committee.ensure_index([('slug', ASCENDING), ('body', ASCENDING)], unique=True)
    
    # person
    self.db.person.ensure_index([('identifier', ASCENDING), ('body', ASCENDING)], unique=True)
    self.db.person.ensure_index([('numeric_id', ASCENDING), ('body', ASCENDING)], unique=True)
    self.db.person.ensure_index([('slug', ASCENDING), ('body', ASCENDING)], unique=True)
    
    # location 
    #self.db.document.ensure_index([('identifier', ASCENDING), ('rs', ASCENDING)], unique=True)
    
    #self.db.sessions.ensure_index([('numeric_id', ASCENDING), ('rs', ASCENDING)], unique=True)
    #self.db.sessions.ensure_index([('url', ASCENDING), ('rs', ASCENDING)], unique=True)
    #self.db.submissions.ensure_index([('numeric_id', ASCENDING), ('rs', ASCENDING)], unique=True)
    #self.db.submissions.ensure_index([('url', ASCENDING), ('rs', ASCENDING)], unique=True)
    #self.db.submissions.ensure_index([('identifier', ASCENDING), ('rs', ASCENDING)], unique=True)
    #self.db.attachments.ensure_index([('identifier', ASCENDING), ('rs', ASCENDING)], unique=True)
    self.db.fs.files.ensure_index(
      [
        ('rs', ASCENDING),
        ('filename', ASCENDING),
        ('uploadDate', DESCENDING),
      ],
      unique=True)

  def erase(self):
    """
    Delete all data from database.
    """
    self.db.queue.remove({'rs': self.config.RS})
    self.db.committee.remove({'rs': self.config.RS})
    self.db.person.remove({'rs': self.config.RS})
    self.db.organisation.remove({'rs': self.config.RS})
    self.db.meeting.remove({'rs': self.config.RS})
    self.db.agendaitem.remove({'rs': self.config.RS})
    self.db.paper.remove({'rs': self.config.RS})
    self.db.document.remove({'rs': self.config.RS})
    self.db.fs.files.remove({'rs': self.config.RS})
    self.db.fs.chunks.remove({'rs': self.config.RS})

  def get_object(self, collection, key, value):
    """
    Return a document
    """
    result = self.db[collection].find_one({key: value,'body':DBRef('body', id=self.body_uid)})
    return result

  def get_object_id(self, collection, key, value):
    """
    Return the ObjectID of a document in the given collection identified
    by the given key:value pair
    """
    result = self.get_object(collection, key, value)
    if result is not None:
      if '_id' in result:
        return result['_id']

  def meeting_exists(self, id):
    if self.get_object_id('meeting', 'identifier', id) is not None:
      return True
    return False

  def agendaitem_exists(self, id):
    if self.get_object_id('agendaitem', 'identifier', id) is not None:
      return True
    return False
  
  def document_exists(self, id):
    if self.get_object_id('document', 'identifier', id) is not None:
      return True
    return False

  def paper_exists(self, id):
    if self.get_object_id('paper', 'identifier', id) is not None:
      return True
    return False
  
  def dereference_object(self, data_dict, object_type, sublist=False):
    if object_type in data_dict:
      # replace object datasets with DBRef dicts
      for n in range(len(data_dict[object_type])):
        save_funct = getattr(self, 'save_' + object_type)
        if sublist:
          oid = save_funct(data_dict[object_type][n][object_type])
        else:
          oid = save_funct(data_dict[object_type][n])
        data_dict[object_type][n] = DBRef(collection=object_type, id=oid)
    return data_dict
  
  
  def save_object(self, data_dict, data_stored, object_type):
    # new object
    if data_stored is None:
      # insert new document
      datatable = getattr(self.db, object_type)
      oid = datatable.insert(data_dict)
      logging.info("%s %s inserted as new", object_type, oid)
      if self.options.verbose:
        sys.stdout.write("%s %s inserted as new\n" % (object_type, oid))
      return oid
    
    # update object
    else:
      berlin = pytz.timezone('Europe/Berlin')
      # compare old and new dict and then send update
      logging.info("%s %s updated with _id %s", object_type, data_dict['identifier'], data_stored['_id'])
      if self.options.verbose:
        sys.stdout.write("%s %s updated with _id %s\n" % (object_type, data_dict['identifier'], data_stored['_id']))
      set_attributes = {}
      for key in data_dict.keys():
        if key in ['last_modified']:
          continue
        if key not in data_stored:
          logging.debug("Key '%s' will be added to %s", key, object_type)
          if self.options.verbose:
            sys.stdout.write("Key '%s' will be added to %s\n" % (key, object_type))
          set_attributes[key] = data_dict[key]
        else:
          # add utc info to datetime objects
          if isinstance(data_stored[key], datetime.datetime):
            data_stored[key] = pytz.utc.localize(data_stored[key])
          if data_stored[key] != data_dict[key]:
            logging.debug("Key '%s' will be updated", key)
            if self.options.verbose:
              sys.stdout.write("Key '%s' in %s has changed\n" % (key, object_type))
            set_attributes[key] = data_dict[key]
      if set_attributes != {}:
        set_attributes['last_modified'] = data_dict['last_modified']
        datatable = getattr(self.db, object_type)
        datatable.update({'_id': data_stored['_id']}, {'$set': set_attributes})
      return data_stored['_id']
  
  def ensure_index(self, ):
    pass
  
  def save_person(self, person):
    person_stored = self.get_object('person', 'numeric_id', person.numeric_id)
    person_dict = person.dict()
    
    # setting body
    person_dict['body'] = [DBRef(collection='body',id=self.body_uid)]
    
    # ensure that there is an identifier
    if 'identifier' not in person_dict:
      if 'numeric_id' not in person_dict:
        logging.critical("Fatal error: neigher identifier nor numeric id avaiable at url %s", person_dict.original_url)
        print "Fatal error: neigher identifier nor numeric id avaiable at url %s" % person_dict.original_url
        return
      else:
        person_dict['identifier'] = str(person_dict['numeric_id'])
    
    # dereference objects
    person_dict = self.dereference_object(person_dict, 'committee', True)
    
    # create slug
    person_dict['slug'] = self.slugify(person_dict['identifier'])
    
    # save data
    return self.save_object(person_dict, person_stored, 'person')

  def create_slug(self, data_dict, object_type):
    current_slug = self.slugify(data_dict['identifier'])
    slug_counter = 0
    while (True):
      dataset = self.get_object(object_type, 'slug', current_slug)
      if dataset:
        if data_dict['identifier'] != dataset['identifier']:
          slug_counter += 1
          current_slug = self.slugify(data_dict['identifier']) + '-' + str(slug_counter)
        else:
          return current_slug
      else:
        return current_slug

  def save_committee(self, committee):
    committee_stored = self.get_object('committee', 'identifier', committee.identifier)
    committee_dict = committee.dict()
    
    # setting body
    committee_dict['body'] = [DBRef(collection='body',id=self.body_uid)]
    
    # ensure that there is an identifier
    if 'identifier' not in committee_dict:
      if 'numeric_id' not in committee_dict:
        logging.critical("Fatal error: neigher identifier nor numeric id avaiable at url %s", committee_dict.original_url)
        print "Fatal error: neigher identifier nor numeric id avaiable at url %s" % committee_dict.original_url
        return
      else:
        committee_dict['identifier'] = str(committee_dict['numeric_id'])
    
    # dereference objects
    
    # create slug
    committee_dict['slug'] = self.create_slug(committee_dict, 'committee')
    
    # save data
    return self.save_object(committee_dict, committee_stored, 'committee')
  
  def save_meeting(self, meeting):
    """
    Write meeting object to database. This means dereferencing all associated objects as DBrefs
    """
    meeting_stored = self.get_object('meeting', 'numeric_id', meeting.numeric_id)
    meeting_dict = meeting.dict()

    # setting body
    meeting_dict['body'] = [DBRef(collection='body',id=self.body_uid)]
    
    # ensure that there is an identifier
    if 'identifier' not in meeting_dict:
      if 'numeric_id' not in meeting_dict:
        logging.critical("Fatal error: neigher identifier nor numeric id avaiable at url %s", meeting_dict.original_url)
        print "Fatal error: neigher identifier nor numeric id avaiable at url %s" % meeting_dict.original_url
        return
      else:
        meeting_dict['identifier'] = str(meeting_dict['numeric_id'])
    
    # dereference items
    meeting_dict = self.dereference_object(meeting_dict, 'committee')
    meeting_dict = self.dereference_object(meeting_dict, 'agendaitem')
    meeting_dict = self.dereference_object(meeting_dict, 'document', True)
    
    # create slug
    meeting_dict['slug'] = self.slugify(meeting_dict['identifier'])
    
    # save data
    return self.save_object(meeting_dict, meeting_stored, 'meeting')

  
  def save_agendaitem(self, agendaitem):
    """
    Write agendaitem object to database. This means dereferencing all associated objects as DBrefs
    """
    agendaitem_stored = self.get_object('agendaitem', 'numeric_id', agendaitem.numeric_id)
    agendaitem_dict = agendaitem.dict()

    # setting body
    agendaitem_dict['body'] = [DBRef(collection='body',id=self.body_uid)]
    
    # ensure that there is an identifier
    if 'identifier' not in agendaitem_dict:
      if 'numeric_id' not in agendaitem_dict:
        logging.critical("Fatal error: neigher identifier nor numeric id avaiable at url %s", agendaitem_dict.original_url)
        print "Fatal error: neigher identifier nor numeric id avaiable at url %s" % agendaitem_dict.original_url
        return
      else:
        agendaitem_dict['identifier'] = agendaitem_dict['numeric_id']
    
    # dereference items
    agendaitem_dict = self.dereference_object(agendaitem_dict, 'paper')
    
    # create slug
    agendaitem_dict['slug'] = str(self.slugify(agendaitem_dict['identifier']))

    return self.save_object(agendaitem_dict, agendaitem_stored, 'agendaitem')
  

  def save_paper(self, paper):
    """Write paper to DB and return ObjectID"""
    paper_stored = self.get_object('paper', 'numeric_id', paper.numeric_id)
    paper_dict = paper.dict()

    paper_dict['body'] = [DBRef(collection='body',id=self.body_uid)]
    
    # ensure that there is an identifier
    if 'identifier' not in paper_dict:
      if 'numeric_id' not in paper_dict:
        logging.critical("Fatal error: neigher identifier nor numeric id avaiable at url %s", paper_dict.original_url)
        print "Fatal error: neigher identifier nor numeric id avaiable at url %s" % paper_dict.original_url
        return
      else:
        paper_dict['identifier'] = str(paper_dict['numeric_id'])
    
    # dereference items
    paper_dict = self.dereference_object(paper_dict, 'paper', True)
    paper_dict = self.dereference_object(paper_dict, 'document', True)
    
    # create slug
    paper_dict['slug'] = self.slugify(paper_dict['identifier'])
    
    return self.save_object(paper_dict, paper_stored, 'paper')
  
  
  def save_document(self, document):
    """
    Write document to DB and return ObjectID.
    - If the document already exists, the existing document
      is updated in the database.
    - If the document.content has changed, a new GridFS file version
      is added.
    - If document is depublished, no new file is stored.
    """
    document_stored = self.get_object('document', 'numeric_id', document.numeric_id)
    document_dict = document.dict()
    document_dict['body'] = [DBRef(collection='body',id=self.body_uid)]
    
    # ensure that there is an identifier
    if 'identifier' not in document_dict:
      if 'numeric_id' not in document_dict:
        logging.critical("Fatal error: neigher identifier nor numeric id avaiable at url %s", paper_dict.original_url)
        print "Fatal error: neigher identifier nor numeric id avaiable at url %s" % paper_dict.original_url
        return
      else:
        document_dict['identifier'] = str(document_dict['numeric_id'])

    # create slug
    document_dict['slug'] = str(self.slugify(document_dict['identifier']))
    
    
    file_changed = False
    if document_stored is not None:
      # document exists in database and must be compared field by field
      logging.info("Document %s is already in db with _id=%s",
        document.identifier,
        str(document_stored['_id']))
      if self.options.verbose:
        sys.stdout.write("Document %s is already in database with _id %s\n" % (document.identifier, str(document_stored['_id'])))
      # check if file is referenced
      file_stored = None
      if 'file' in document_stored:
        # assuming DBRef in document.file
        assert type(document_stored['file']) == DBRef
        file_stored = self.db.fs.files.find_one({'_id': document_stored['file'].id})
      if file_stored is not None and 'content' in document_dict:
        # compare stored and submitted file
        if file_stored['length'] != len(document.content):
          file_changed = True
        elif file_stored['md5'] != md5(document.content).hexdigest():
          file_changed = True
    # Create new file version (if necessary)
    if ((file_changed and 'depublication' not in document_stored)
      or (document_stored is None)) and document.content:
      file_oid = self.fs.put(document.content,
        filename=document.slug,
        body=DBRef('body', self.body_uid))
      logging.info("New file version stored with _id=%s", str(file_oid))
      if self.options.verbose:
        sys.stdout.write("New file version stored with _id %s\n" % str(file_oid))
      document_dict['file'] = DBRef(collection='fs.files', id=file_oid)

    # erase file content (since stored elsewhere above)
    if 'content' in document_dict:
      del document_dict['content']
    
    oid = None
    if document_stored is None:
      # insert new
      oid = self.db.document.insert(document_dict)
      logging.info("Document %s inserted with _id %s",
        document.identifier, str(oid))
      if self.options.verbose:
        sys.stdout.write("Document %s inserted with _id %s\n" % (document.identifier, str(oid)))
    else:
      # Only do partial update
      oid = document_stored['_id']
      set_attributes = {}
      for key in document_dict.keys():
        if key in ['last_modified']:
          continue
        if key not in document_stored:
          #print "Key '%s' is not in stored document." % key
          set_attributes[key] = document_dict[key]
        else:
          # add utc info to datetime objects
          if isinstance(document_stored[key], datetime.datetime):
            document_stored[key] = pytz.utc.localize(document_stored[key])
          if document_stored[key] != document_dict[key]:
            logging.debug("Key '%s' will be updated", key)
            if self.options.verbose:
              sys.stdout.write("Key '%s' in document has changed\n" % key)
            set_attributes[key] = document_stored[key]
      if 'file' not in document_dict and 'file' in document_stored:
          set_attributes['file'] = document_stored['file']
      if file_changed or set_attributes != {}:
        set_attributes['last_modified'] = document_dict['last_modified']
        self.db.document.update({'_id': oid},
          {'$set': set_attributes})
    return oid

  def slugify(self, identifier):
    identifier = unicode(identifier)
    identifier = identifier.replace('/', '-')
    identifier = identifier.replace(' ', '-')
    result = []
    for word in self.slugify_re.split(identifier.lower()):
      word = word.encode('translit/long')
      if word:
        result.append(word)
    return unicode('-'.join(result))
  
  def queue_status(self):
    """
    Prints out information on the queue
    """
    aggregate = self.db.queue.aggregate([
      {
        "$group": {
          "_id": {
            "rs": "$rs",
            "status": "$status",
            "qname": "$qname"
          },
          "count": {"$sum": 1}
        }
      },
      {
        "$sort": {"_id.rs": 1}
      }])
    rs = None
    for entry in aggregate['result']:
      if entry['_id']['rs'] != rs:
        rs = entry['_id']['rs']
        print "RS: %s" % rs
      print "Queue %s, status %s: %d jobs" % (
        entry['_id']['qname'], entry['_id']['status'], entry['count'])
