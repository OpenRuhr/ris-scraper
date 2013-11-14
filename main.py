# encoding: utf-8

"""
Copyright (c) 2012 Marian Steinbach, Ernesto Ruge

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

import argparse
from risscraper.scrapersessionnet import ScraperSessionNet
from risscraper.scraperallris import ScraperAllRis
import inspect
import os
import datetime
import sys
import importlib
import logging
import calendar

cmd_subfolder = os.path.realpath(os.path.abspath(os.path.join(os.path.split(inspect.getfile( inspect.currentframe() ))[0],"city")))
if cmd_subfolder not in sys.path:
    sys.path.insert(0, cmd_subfolder)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Scrape Dein Ratsinformationssystem')
    #parser.add_argument('--config', '-c', dest='configname', default='config',
    #        help=("Name of the configuration module to use (e.g. 'config_koeln' for file 'config_koeln.py'). " +
    #            "Default: 'config'"))
    parser.add_argument('--city', '-c', dest='city',
            help=("Name of the city"))
    parser.add_argument('--verbose', '-v', action='count', default=0, dest="verbose")
    parser.add_argument('--queue', '-q', dest="workfromqueue", action="store_true",
            default=False, help=('Set this flag to activate "greedy" scraping. This means that ' +
                'links from sessions to submissions are followed. This is implied ' +
                'if --start is given, otherwise it is off by default.'))
    parser.add_argument('--start', dest="start_month",
            default=False, help=('Find sessions and related content starting in this month. ' +
                'Format: "YYYY-MM". When this is used, the -q parameter is implied.'))
    parser.add_argument('--end', dest="end_month",
            default=False, help=('Find sessions and related content up to this month. ' +
                'Requires --start parameter to be set, too. Format: "YYYY-MM"'))
    parser.add_argument('--sessionid', dest="session_id",
            default=False, help='Scrape a specific session, identified by its numeric ID')
    parser.add_argument('--sessionurl', dest="session_url",
            default=False, help='Scrape a specific session, identified by its detail page URL')
    parser.add_argument('--submissionid', dest="submission_id",
            default=False, help='Scrape a specific submission, identified by its numeric ID')
    parser.add_argument('--submissionurl', dest="submission_url",
            default=False, help='Scrape a specific submission, identified by its detail page URL')
    parser.add_argument('--erase', dest="erase_db", action="store_true",
            default=False, help='Erase all database content before start. Caution!')
    parser.add_argument('--status', dest="status", action="store_true",
            default=False, help='Print out queue status')
    options = parser.parse_args()

    if options.city:
        try:
            
            config = __import__(options.city)
        except ImportError, e:
            if "No module named" in str(e):
                sys.stderr.write("ERROR: Configuration module not found. Make sure you have your config file\n")
                sys.stderr.write("       named '%s.py' in the ./city folder.\n" % options.city)
            sys.exit(1)

    # set up logging
    logfile = 'scrapearis.log'
    if config.LOG_BASE_DIR is not None:
        now = datetime.datetime.utcnow()
        logfile = '%s%s-%s-%s.log' % (config.LOG_BASE_DIR, config.CITY, config.RS, now.strftime('%Y%m%d-%H%M'))
    levels = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }
    loglevel = 'INFO'
    if config.LOG_LEVEL is not None:
        loglevel = config.LOG_LEVEL
    logging.basicConfig(
        filename=logfile,
        level=levels[loglevel],
        format='%(asctime)s %(name)s %(levelname)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S')
    logging.info('Starting scraper with configuration from "%s" and loglevel "%s"',
        options.city, loglevel)

    db = None
    if config.DB_TYPE == 'mongodb':
        import db.mongodb
        db = db.mongodb.MongoDatabase(config, options)
        db.setup()

    if options.status:
        db.queue_status()

    if options.erase_db:
        print "Erasing database"
        db.erase()
    
    # TODO: Autodetect
    if config.SCRAPER_TYPE == 'SESSIONNET':
        scraper = ScraperSessionNet(config, db, options)
    elif config.SCRAPER_TYPE == 'ALLRIS':
        scraper = ScraperAllRis(config, db, options)
    
    scraper.guess_system()

    if options.session_id:
        scraper.get_session(session_id=int(options.session_id))

    if options.session_url:
        scraper.get_session(session_url=options.session_url)

    if options.submission_id:
        scraper.get_submission(submission_id=int(options.submission_id))

    if options.submission_url:
        scraper.get_submission(submission_url=options.submission_url)

    if options.start_month:
        options.workfromqueue = True
        try:
            options.start_month = datetime.datetime.strptime(options.start_month, '%Y-%m')
        except ValueError:
            sys.stderr.write("Bad format or invalid month for --start parameter. Use 'YYYY-MM'.\n")
            sys.exit()
        if options.end_month:
            try:
                options.end_month = datetime.datetime.strptime("%s-%s" % (options.end_month, calendar.monthrange(int(options.end_month[0:4]), int(options.end_month[5:7]))[1]), '%Y-%m-%d')
            except ValueError:
                sys.stderr.write("Bad format or invalid month for --end parameter. Use 'YYYY-MM'.\n")
                sys.exit()
            if options.end_month < options.start_month:
                sys.stderr.write("Error with --start and --end parameter: end month should be after start month.\n")
                sys.exit()
        else:
            options.end_month = options.start_month
        scraper.find_sessions(start_date=options.start_month, end_date=options.end_month)

    if options.workfromqueue:
        scraper.work_from_queue()

    logging.info('Scraper finished.')
