import datetime
import json
import os
import re
import requests
import time
import traceback

from threading import Thread
from css_html_js_minify import html_minify
from flask import abort
from flask import Blueprint
from flask import redirect
from flask import render_template
from flask import Response
from flask import send_from_directory
from pytz import timezone

CURL_CACHING = False
CACHE_AGE = 60    # Daily refresh

scrape_thread = None

HALLS = [{
    'name': 'College Nine/John R Lewis',
    'code': '40',
    'hours_url': '/hours/college-nine-john-r-lewis',
}, {
    'name': 'Cowell/Stevenson',
    'code': '05',
    'hours_url': '/hours/cowell-stevenson',
}, {
    'name': 'Crown/Merrill',
    'code': '20',
    'hours_url': '/hours/crown-merrill',
}, {
    'name': 'Porter/Kresge',
    'code': '25',
    'hours_url': '/hours/porter-kresge',
}, {
    'name': 'Carson/Oakes',
    'code': '30',
    'hours_url': '/hours/carson-oakes',
}]

LEGEND = {
    'alcohol': '🍷',
    'beef': '🐄',
    'eggs': '🥚',
    'fish': '🐟',
    'gluten': '🍞',
    'halal': '🤲',
    'milk': '🥛',
    'nuts': '🥜',
    'pork': '🐖',
    'sesame': '🟤',
    'shellfish': '🦀',
    'soy': '🟢',
    'treenut': '🌳',
    'vegan': '🌱',
    'veggie': '🥦',
    'unknown': '❓',
}

def render(template, **params):
    html = render_template(template, **params)

    # very large pages take forever to minify
    # should probably use a different library
    if re.search(r'.html$', template) and len(html) < 1000000:
        html = html_minify(html)

    return html

def cache_age(c):
    age = time.time() - c
    if age < 2:
        return 'just now'
    if age < 60 * 1.5:
        return f'{age:.0f} seconds ago'
    if age < 60 * 90:
        return f'{age / 60:.0f} minutes ago'
    if age < 60 * 60 * 24:
        return f'{age / 3660:.1f} hours ago'
    return 'more than a day ago'

def jsonify(val):
    return json.dumps(val)

def strftime(date, format):
    return date.strftime(format)

def curly(url, code, date):
    if not os.path.exists('tmp'):
        os.makedirs('tmp')

    file = f'tmp/ucsc-output-{date}-{code}.html'

    if not (CURL_CACHING and os.path.exists(file)):
        cookies = {
            'WebInaCartLocation': '',
            'WebInaCartDates': '',
            'WebInaCartMeals': '',
            'WebInaCartRecipes': '',
            'WebInaCartQtys': '',
        }

        response = requests.get(url, cookies = cookies, verify=False)

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
    i = 0

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
                struct[-1]['cats'][-1]['foods'] += [{
                    'name': food,
                    'legend': {},
                    'idx': f'{date}-{code}-{i}',
                }]
                i += 1

        m = re.search('LegendImages/([^\.]+)', l)
        if m:
            struct[-1]['cats'][-1]['foods'][-1]['legend'][m.group(1)] = 1

    new_struct = []
    for meal in struct:
        if len(meal['cats']) > 0:
            new_cats = []
            for cat in meal['cats']:
                if len(cat['foods']) > 0:
                    for f in cat['foods']:
                        if len(f['legend']) == 0:
                            f['legend'] = {'unknown': 1}
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
            'hours_url': hall['hours_url'],
            'meals': meals,
        }

    return None

def ucsc_halls_json(val = None):
    if not os.path.exists('tmp'):
            os.makedirs('tmp')
    if val:
        f = open('tmp/ucsc-cache.json', 'w')
        f.write(val)
        f.close()

    else:
        try:
            f = open('tmp/ucsc-cache.json')
            val = f.read()
            f.close()
        except:
            val = ''

    return val or '{}'

def getcache():
    cache = ucsc_halls_json()
    cache = json.loads(cache)
    return cache

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
        meals_lookup[m] = i
        i += 1

    return (all_meals, meals_lookup)

ucsc = Blueprint('ucsc', __name__)
@ucsc.route('/', methods = ['GET'])
def ucscRoute():
    try:
        cache = getcache()
        calendar = []

        age = cache.get('time') or 0
        age = time.time() - age
        if age < CACHE_AGE:
            print('Cache is fresh')
        else:
            print('Cache expired! Getting menu...')
            if not scrape_thread.is_alive():
                scrape_thread = Thread(target=scrape_menus, args=("PRINT_OUTPUT",), daemon=True)
                scrape_thread.start()

        today = datetime.datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)

        if 'dates' not in cache:
            return Response('Error: Cache invalid! Wait a few seconds for it to refresh, and then reload the page.')
        
        for date in sorted(list(cache['dates'])):
            date_obj = datetime.datetime.strptime(date, '%Y-%m-%d')
            if date_obj < today:    # If cache contains older days, then skip til today's date
                continue

            calendar.append({
                'date': date_obj,
                'halls': cache['dates'][date]['halls'],
            })

        (all_meals, meals_lookup) = get_all_meals(calendar)

        return render('ucsc.html',
            calendar = calendar,
            all_meals = all_meals,
            meals_lookup = meals_lookup,
            halls = HALLS,
            legend = LEGEND,
            cache_time = cache['time'],
            strftime = strftime,
            jsonify = jsonify,
            cache_age = cache_age,
        )

    except BaseException as e:
        error = repr(e) + '\n\n'
        error += traceback.format_exc()
        return render('ucsc.html', error = error)

class Encoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
            return obj.isoformat()
        return json.JSONEncoder.default(self, obj)

def jdump(obj):
    return json.dumps(obj, cls = Encoder)

@ucsc.route('/api', methods = ['GET'])
def ucscJSONRoute():
    try:
        cache = getcache()
        calendar = []
        for date in sorted(list(cache['dates'])):
            calendar.append({
                'date': datetime.datetime.strptime(date, '%Y-%m-%d'),
                'halls': cache['dates'][date]['halls'],
            })

        return Response(
            response = jdump(calendar),
            status = 200,
            mimetype = 'application/json'
        )

    except BaseException as e:
        error = repr(e) + '\n\n'
        error += traceback.format_exc()
        return render('ucsc.html', error = error)

@ucsc.route('/fullcrawl', methods = ['GET'])
def fullcrawl(print_output = None):
    cache = getcache()

    # try:
    #     print('res')

    #     res = requests.get('https://nutrition.sa.ucsc.edu/shortmenu.aspx?sName=UC+Santa+Cruz+Dining&locationNum=40&locationName=John+R.+Lewis+%26+College+Nine+Dining+Hall&naFlag=1')
    #     print('res', res)
    #     if requests.get('https://nutrition.sa.ucsc.edu', timeout=15).status_code != requests.codes['ok']:
    #         return redirect('/')    # If unable to access site just fallback to cache and hope something exists in it
    # except Exception as e:
    #     if print_output:
    #         print("Unable to access nutrition website: " + str(e) + "\nFalling back to cache...")
    #     return redirect('/')
    
    age = cache.get('time') or 0
    age = time.time() - age
    if age < CACHE_AGE:
        if print_output:
            print('Cache is fresh')
        return redirect('/')
    if print_output:
        print('Cache expired! Getting menu...')


    print('Running fullcrawl in background thread...')
    scrape_thread = Thread(target=scrape_menus, args=(print_output,), daemon=True)
    scrape_thread.start()

    return redirect('/')

def scrape_menus(print_output=None):
    cache = {
        'dates': {}
    }

    today = datetime.datetime.now().astimezone(timezone('US/Pacific')).date()
    for i in range(0, 8):
        date = today + datetime.timedelta(days = i)
        date_key = date.strftime('%Y-%m-%d')
        if print_output:
            print(date_key)

        halls = []
        for hall in HALLS:
            if print_output:
                print(f'  {hall["name"]}')

            h = gethall(hall, date)
            if h:
                halls += [h]

        cache['dates'][date_key] = {
            'halls': halls,
        }

    cache['time'] = time.time()
    print(json.dumps(cache))
    ucsc_halls_json(json.dumps(cache))

HOURS_LOOKUP = {
    'college-nine-john-r-lewis': 'ninelewis',
    'porter-kresge': 'porterdh',
    'cowell-stevenson': 'csdh',
    'crown-merrill': 'cmdh',
    'carson-oakes': 'rodh'
}

@ucsc.route('/hours', methods = ['GET'])
@ucsc.route('/hours/<key>', methods = ['GET'])
def hours(key = None):
    if not key:
        key = 'ninelewis|porterdh|cmdh|csdh|rodh'
    elif key not in HOURS_LOOKUP:
        return abort(404)
    else:
        key = HOURS_LOOKUP[key]

    response = requests.get('https://dining.ucsc.edu/eat/')
    html = response.content.decode('utf8')
    html = re.sub('display: block', 'display: table', html)
    html = re.sub('display: none', 'display: block', html)
    html = re.sub('<p>(\*.*?)</p>', r'<p class="footnote">\1</p>', html)

    halls = re.findall(f'(?s)<div id="(?:{key})".*?<p class="footnote">.*?</p>', html)

    return render('hours.html', halls_html = halls)

@ucsc.route('/favicon.ico')
def favicon():
    return send_from_directory(ucsc.root_path, 'slug.png')

def main():
    try:
        fullcrawl('PRINT_OUTPUT')

    except BaseException as e:
        print('UCSC Job Failed')
        print(repr(e))
        print(traceback.format_exc())

if __name__ == '__main__':
    main()