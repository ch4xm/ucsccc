import datetime
import json
import os
import re
import requests
import subprocess
import time
import traceback

from css_html_js_minify import html_minify
from flask import Blueprint
from flask import render_template
from pytz import timezone

CURL_CACHING = False
CACHE_AGE = 900

HALLS = [
    {'code': '40', 'name': 'JRLC/College 9'},
    {'code': '25', 'name': 'Porter/Kresge'},
    {'code': '05', 'name': 'Cowell/Stevenson'},
    {'code': '20', 'name': 'Crown/Merrill'},
]

def render(template, **params):
    html = render_template(template, **params)

    # very large pages take forever to minify
    # should probably use a different library
    if re.search(r'.html$', template) and len(html) < 1000000:
        html = html_minify(html)

    return html

def jsonify(val):
    return json.dumps(val)

def strftime(date, format):
    return date.strftime(format)

def curly(url, code, date):
    file = f'/tmp/ucsc-output-{date}-{code}.html'

    if not (CURL_CACHING and os.path.exists(file)):
        cookies = {
            'WebInaCartLocation': '',
            'WebInaCartDates': '',
            'WebInaCartMeals': '',
            'WebInaCartRecipes': '',
            'WebInaCartQtys': '',
        }

        response = requests.get(url, cookies = cookies)

        f = open(file, 'wb')
        f.write(response.content)
        f.close()

    f = open(file)
    result = f.read()
    f.close()
    return result

def getmeals(code, date):
    date_formatted = date.strftime('%m-%d-%Y')
    date_esc = date_formatted.replace('-', '%2f')
    url = (
        'https://nutrition.sa.ucsc.edu/shortmenu.aspx'
        '?naFlag=1'
        f'&locationNum={code}'
        f'&dtdate={date_esc}'
    )

    output = curly(url, code, date_formatted)

    struct = []

    for l in output.split('\n'):
        l = l.replace('&nbsp;', ' ')
        l = l.replace('--', '')
        m = re.search('shortmenu(meals|cats|recipes).*>\s*([^<]+?)\s*<', l)
        if m:
            level = m.group(1)
            food = m.group(2)

            if level == 'meals':
                struct += [{
                    'meal': food,
                    'cats': [],
                }]

            elif level == 'cats':
                struct[-1]['cats'] += [{
                    'cat': food,
                    'foods': [],
                }]

            elif level == 'recipes':
                struct[-1]['cats'][-1]['foods'] += [food]

    new_struct = []
    for meal in struct:
        if len(meal['cats']) > 0:
            new_cats = []
            for cat in meal['cats']:
                if len(cat['foods']) > 0:
                    new_cats.append(cat)

            if len(new_cats) > 0:
                new_struct.append({
                    'meal': meal['meal'],
                    'cats': new_cats,
                })

    return new_struct

def gethall(hall, date):
    meals = getmeals(hall['code'], date)
    if len(meals) > 0:
        return {
            'name': hall['name'],
            'code': hall['code'],
            'meals': meals,
        }

    return None

def ucsc_halls_json(val = None):
    if val:
        f = open('/tmp/ucsc-cache.json', 'w')
        f.write(val)
        f.close()

    else:
        try:
            f = open('/tmp/ucsc-cache.json')
            val = f.read()
            f.close()
        except:
            val = ''

    return val or '{}'

def getcache():
    cache = ucsc_halls_json()
    cache = json.loads(cache)
    return cache

def getcalendar():
    cache = getcache()
    calendar = []
    for date in sorted(list(cache)):
        calendar.append({
            'date': datetime.datetime.strptime(date, '%Y-%m-%d'),
            'halls': cache[date]['halls'],
        })

    return calendar

def gethalls(date):
    cache = getcache()

    key = date.strftime('%Y-%m-%d')
    if cache.get(key):
        age = time.time() - cache[key]['time']
        if age < CACHE_AGE:
            return cache[key]['halls']

    halls = []
    for hall in HALLS:
        h = gethall(hall, date)
        if h:
            halls += [h]

    cache[key] = {
        'time': time.time(),
        'halls': halls,
    }

    to_clean = []
    for k in cache:
        age = time.time() - cache[k]['time']
        if age >= CACHE_AGE:
            to_clean.append(k)
    for k in to_clean:
        del(cache[k])

    ucsc_halls_json(json.dumps(cache))

    return halls

def get_all_meals(calendar):
    meals = set()
    for d in calendar:
        for h in d['halls']:
            for m in h['meals']:
                meals.add(m['meal'])

    all_meals = []
    for m in ['Breakfast', 'Lunch', 'Dinner', 'Late Night']:
        if m in meals:
            all_meals.append(m)
            meals.remove(m)

    all_meals += sorted(list(meals))

    meals_lookup = {}
    i = 0
    for m in all_meals:
        meals_lookup[m] = f'meal-{i}'
        i += 1

    return (all_meals, meals_lookup)

ucsc = Blueprint('ucsc', __name__)
@ucsc.route('/', methods = ['GET'])
def ucscRoute():
    try:
        calendar = getcalendar()

    except BaseException as e:
        error = repr(e) + '\n\n'
        error += traceback.format_exc()
        return render('ucsc.html', error = error)

    (all_meals, meals_lookup) = get_all_meals(calendar)

    return render('ucsc.html',
        calendar = calendar,
        all_meals = all_meals,
        meals_lookup = meals_lookup,
        halls = HALLS,
        strftime = strftime,
        jsonify = jsonify,
    )

@ucsc.route('/fullcrawl', methods = ['GET'])
def fullcrawl(print_output = None):
    today = datetime.datetime.now()
    today = today.astimezone(timezone('US/Pacific')).date()
    html = ''
    for i in range(0, 8):
        date = today + datetime.timedelta(days = i)
        if print_output:
            print(date)
        else:
            html += f'Crawled {date}<br>'
        gethalls(date)

    return html

def main():
    try:
        fullcrawl('PRINT_OUTPUT')

    except BaseException as e:
        print('UCSC Job Failed')
        print(repr(e))
        print(traceback.format_exc())

if __name__ == '__main__':
    main()
