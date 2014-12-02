# encoding: utf-8

import types



dict1 = {
  'key1': 'wert1',
  'key2': 'wert2',
  'subdict1': {
    'key4': 'wert4',
    'key5': 'wert5a',
    'key7': 'wert7'
  }
}

dict2 = {
  'key1': 'wert1',
  'key2': 'wert2',
  'subdict1': {
    'key4': 'wert4',
    'key5': 'wert5b'
  },
  'key6': 'wert6'
}

print dict1
print dict2
print merge_dict(dict1, dict2)