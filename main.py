# -*- coding: utf-8 -*-
import csv
import os
import re
import subprocess
import sys
from datetime import datetime
output_lines = []
ANSI_RE = re.compile(r"\033\[[0-9;]*m")

def log(text="", to_terminal=True):

    if to_terminal:
        print(text)

    output_lines.append(ANSI_RE.sub("", str(text)))
from collections import defaultdict


def get_score_diff_recommendation(diff):

    return "単勝6倍以上", "3連複軸一等流し"


def normalize_trainer_name(value):
    return re.sub(r"\s+", "", str(value or "").strip())


def trainer_bonus_from_rates(win_rate, place_rate):
    try:
        win_rate = float(str(win_rate).replace("%", "").strip())
        place_rate = float(str(place_rate).replace("%", "").strip())
    except:
        return 0.0

    combined = place_rate * 0.75 + win_rate * 1.25

    if combined >= 50:
        return 3.0
    if combined >= 46:
        return 2.5
    if combined >= 42:
        return 2.0
    if combined >= 38:
        return 1.0
    if combined >= 34:
        return 0.5

    return 0.0


def load_trainer_bonuses():
    bonuses = defaultdict(float)
    path = get_path("調教師.csv")

    if not os.path.exists(path):
        return bonuses

    with open(path, "r", encoding="cp932", errors="ignore", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            bonus = trainer_bonus_from_rates(
                row.get("勝率", ""),
                row.get("複勝率", "")
            )

            for key in [
                row.get("名前(ターゲット内表記)", ""),
                row.get("フルネーム(JRA-VANデータ内表記)", "")
            ]:
                name = normalize_trainer_name(key)

                if name:
                    bonuses[name] = bonus

    return bonuses

# --- 1. 定数・DB設定 ---
CORRELATION_DB = {
    "芝": {"東京": {"fast": 33.4, "mid": 34.2}, "京都": {"fast": 33.8, "mid": 34.5}, "中山": {"fast": 34.2, "mid": 35.0}},
    "ダート": {"東京": {"fast": 35.5, "mid": 36.5}, "京都": {"fast": 36.0, "mid": 37.0}, "中山": {"fast": 37.3, "mid": 38.2}}
}

ROTATION_MAP = {
    "東京": "左", "新潟": "左", "中京": "左",
    "中山": "右", "京都": "右", "阪神": "右", "小倉": "右", "福島": "右", "札幌": "右", "函館": "右"
}

CLASSIC_RACES = ["日本ダービー", "東京優駿", "皐月賞", "菊花賞", "桜花賞", "優駿牝馬", "オークス"]

# 競馬場ファイル名マッピング
VENUE_FILE_MAP = {
    "東京": "rap_tokyo.csv", "中山": "rap_nakayama.csv", "京都": "rap_kyoto.csv", 
    "阪神": "rap_hanshin.csv", "中京": "rap_chukyo.csv", "小倉": "rap_kokura.csv", 
    "新潟": "rap_niigata.csv", "福島": "rap_hukusima.csv", "札幌": "rap_sapporo.csv", "函館": "rap_hakodate.csv"
}

class VenueStatsMaster:
    def __init__(self, file_path):
        self.stats = {}
        if not os.path.exists(file_path): return
        try:
            with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                content = f.read()
                sections = re.split(r'(\w{2}(?:芝|ダート)\d+m)', content)
                for i in range(1, len(sections), 2):
                    course_key = sections[i].replace("ダート", "ダ")
                    self.stats[course_key] = self._parse_section(sections[i+1])
        except: pass

    def _parse_section(self, text):
        data = {"good_waku": []}
        waku_lines = re.findall(r'(\d)\t[\d-]+\t(\d+(?:\.\d+)?)%', text)
        for w, rate in waku_lines:
            if float(rate) >= 8.0: data["good_waku"].append(int(w))
        return data

class WeeklyBiasMaster:
    def __init__(self, file_path):
        self.biases = {}
        file_paths = file_path if isinstance(file_path, (list, tuple)) else [file_path]
        for path in file_paths:
            self._load_file(path)

    def _load_file(self, file_path):
        if not file_path or not os.path.exists(file_path):
            return
        encodings = ['utf-8-sig', 'cp932']

        for enc in encodings:
            try:
                with open(file_path, 'r', encoding=enc, newline='') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        place = str(row.get('競馬場', '')).strip()
                        track = str(row.get('芝ダ', '')).strip().replace('ダート', 'ダ')
                        week = str(row.get('開催週', '')).strip()
                        if not place or not track:
                            continue

                        bias = {
                            'style': {
                                '逃げ': self._to_float(row.get('脚質指数(逃げ)')),
                                '先行': self._to_float(row.get('脚質指数(先行)')),
                                '差し': self._to_float(row.get('脚質指数(差し)')),
                                '追込': self._to_float(row.get('脚質指数(追込)')),
                            },
                            'waku': {
                                'inner': self._to_float(row.get('枠指数(内1-2)')),
                                'middle_inner': self._to_float(row.get('枠指数(中3-4)')),
                                'middle_outer': self._to_float(row.get('枠指数(中5-6)')),
                                'outer': self._to_float(row.get('枠指数(外7-8)')),
                            },
                            'agari': self._to_float(row.get('上がり重要度')),
                            'baba': self._to_float(row.get('馬場タイプスコア')),
                            'extra': {
                                'front': self._pick_float(row, [
                                    '前有利補正', '前有利指数', 'front_bias_bonus', 'front_bias_score'
                                ]),
                                'closer': self._pick_float(row, [
                                    '差し有利補正', '差し有利指数', 'closer_bias_bonus', 'closer_bias_score'
                                ]),
                                'inside': self._pick_float(row, [
                                    '内有利補正', '内外バイアス指数', 'inside_bias_bonus', 'inside_bias_score'
                                ]),
                                'outside': self._pick_float(row, [
                                    '外有利補正', 'outside_bias_bonus', 'outside_bias_score'
                                ]),
                                'longshot': self._pick_float(row, [
                                    '穴馬補正', '穴馬バイアス指数', 'longshot_bias_bonus', 'longshot_bias_score'
                                ]),
                                'favorite': self._pick_float(row, [
                                    '人気信頼補正', '人気信頼度', 'favorite_bonus', 'favorite_score'
                                ]),
                                'total': self._pick_float(row, [
                                    '総合補正', '総合点', 'total_bias_bonus', 'total_score'
                                ]),
                            },
                        }
                        self.biases[(place, track, week)] = bias
                        if not week:
                            self.biases[(place, track)] = bias
                break
            except: continue

    def _to_float(self, value):
        try:
            return float(str(value).strip())
        except:
            return 0.0

    def _pick_float(self, row, names):
        for name in names:
            if name in row and str(row.get(name, '')).strip() != '':
                return self._to_float(row.get(name))
        return 0.0

    def _scaled_extra(self, value, scale=1.0, limit=4.0):
        if value == 0:
            return 0.0
        # 25〜40点満点系の指数は10分の1、100点系の指数は50を基準に小さく補正する。
        if 20 < abs(value) <= 40:
            value = value / 10.0
        elif abs(value) > 40:
            value = (value - 50.0) / 10.0
        return max(min(value * scale, limit), -limit)

    def get_bias(self, place, track, week=''):
        place = str(place or '').strip()
        track = str(track or '').strip().replace('ダート', 'ダ')
        week = str(week or '').strip()
        return (
            self.biases.get((place, track, week))
            or self.biases.get((place, track, ''))
            or self.biases.get((place, track))
        )

    def get_score(self, place, track, waku, style, week=''):
        bias = self.get_bias(place, track, week)
        if not bias:
            return 0.0

        score = bias.get('baba', 0.0)

        style = str(style or '')
        for style_name, style_score in bias.get('style', {}).items():
            if style_name in style:
                score += style_score
                break

        if any(word in style for word in ['差し', '追込', '中団', '後方', '上がり', '末脚']):
            score += bias.get('agari', 0.0)

        try:
            waku_num = int(waku)
            if waku_num <= 2:
                score += bias['waku'].get('inner', 0.0)
            elif waku_num <= 4:
                score += bias['waku'].get('middle_inner', 0.0)
            elif waku_num <= 6:
                score += bias['waku'].get('middle_outer', 0.0)
            else:
                score += bias['waku'].get('outer', 0.0)
        except:
            pass

        extra = bias.get('extra', {})
        if any(word in style for word in ['逃げ', '先行']):
            score += self._scaled_extra(extra.get('front', 0.0), limit=4.0)
            score -= self._scaled_extra(extra.get('closer', 0.0), scale=0.6, limit=3.0)
        elif any(word in style for word in ['差し', '追込', '中団', '後方', '上がり', '末脚']):
            score += self._scaled_extra(extra.get('closer', 0.0), limit=4.0)
            score -= self._scaled_extra(extra.get('front', 0.0), scale=0.6, limit=3.0)

        try:
            waku_num = int(waku)
            if waku_num <= 4:
                score += self._scaled_extra(extra.get('inside', 0.0), limit=3.0)
                score -= self._scaled_extra(extra.get('outside', 0.0), scale=0.6, limit=2.0)
            else:
                score += self._scaled_extra(extra.get('outside', 0.0), limit=3.0)
                score -= self._scaled_extra(extra.get('inside', 0.0), scale=0.6, limit=2.0)
        except:
            pass

        score += self._scaled_extra(extra.get('total', 0.0), scale=0.4, limit=2.0)

        return round(score, 1)

class TodayTrackBiasMaster:
    def __init__(self, file_path):
        self.biases = {}
        if not os.path.exists(file_path):
            return

        for enc in ['utf-8-sig', 'cp932']:
            try:
                with open(file_path, 'r', encoding=enc, errors='ignore', newline='') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        group_type = str(row.get('group_type', '')).strip()
                        if group_type not in {'距離別', '距離帯別', '芝ダ障害別', '競馬場別'}:
                            continue

                        place = str(row.get('course', '')).strip()
                        surface = str(row.get('surface', '')).strip().replace('ダート', 'ダ')
                        distance = self._to_int(row.get('distance'))
                        distance_band = str(row.get('distance_band', '')).strip()
                        if not place:
                            continue

                        bias = {
                            'group_type': group_type,
                            'front_diff': self._to_float(row.get('front_bias_diff')),
                            'inside_diff': self._to_float(row.get('inside_bias_diff')),
                            'longshot_count': self._to_int(row.get('longshot_good_count'), 0),
                            'favorite_rate': self._to_float(row.get('favorite_place_rate')),
                            'sample_score': self._to_float(row.get('sample_score')),
                            'total_score': self._to_float(row.get('total_score')),
                            'judgement': str(row.get('judgement', '')).strip(),
                        }

                        keys = []
                        if group_type == '距離別' and surface and distance:
                            keys.append(('distance', place, surface, str(distance)))
                        elif group_type == '距離帯別' and surface and distance_band:
                            keys.append(('band', place, surface, distance_band))
                        elif group_type == '芝ダ障害別' and surface:
                            keys.append(('surface', place, surface))
                        elif group_type == '競馬場別':
                            keys.append(('place', place))

                        for key in keys:
                            self.biases[key] = bias
                break
            except:
                continue

    def _to_float(self, value, default=0.0):
        try:
            return float(str(value).strip())
        except:
            return default

    def _to_int(self, value, default=None):
        match = re.search(r'\d+', str(value or ''))
        return int(match.group()) if match else default

    def _distance_band(self, surface, distance):
        if surface == '障害':
            return '障害'
        try:
            distance = int(distance)
        except:
            return ''
        if 1000 <= distance <= 1400:
            return '短距離'
        if 1600 <= distance <= 1800:
            return 'マイル'
        if 2000 <= distance <= 2200:
            return '中距離'
        if distance >= 2400:
            return '長距離'
        return 'その他'

    def get_bias(self, place, surface, distance):
        place = str(place or '').strip()
        surface = str(surface or '').strip().replace('ダート', 'ダ')
        distance_text = str(self._to_int(distance, '') or '')
        band = self._distance_band(surface, distance_text)
        return (
            self.biases.get(('distance', place, surface, distance_text))
            or self.biases.get(('band', place, surface, band))
            or self.biases.get(('surface', place, surface))
            or self.biases.get(('place', place))
        )

    def get_score(self, place, surface, distance, waku, style, popularity=None):
        bias = self.get_bias(place, surface, distance)
        if not bias:
            return 0.0

        sample_factor = min(max(bias.get('sample_score', 0.0) / 5.0, 0.2), 1.0)
        strength_factor = min(max(bias.get('total_score', 0.0) / 100.0, 0.0), 1.0)
        score = 0.0

        style = str(style or '')
        front_diff = bias.get('front_diff', 0.0)
        if any(x in style for x in ['逃げ', '先行']):
            if front_diff >= 0.30:
                score += 5.0
            elif front_diff >= 0.20:
                score += 4.0
            elif front_diff >= 0.10:
                score += 3.0
            elif front_diff <= -0.10:
                score -= 3.0
        elif any(x in style for x in ['差し', '追込', '後方']):
            if front_diff <= -0.20:
                score += 4.0
            elif front_diff <= -0.10:
                score += 3.0
            elif front_diff >= 0.20:
                score -= 3.0

        try:
            waku_num = int(waku)
            inside_diff = bias.get('inside_diff', 0.0)
            if waku_num <= 4:
                if inside_diff >= 0.15:
                    score += 3.0
                elif inside_diff >= 0.05:
                    score += 2.0
                elif inside_diff <= -0.15:
                    score -= 3.0
                elif inside_diff <= -0.05:
                    score -= 2.0
            elif waku_num >= 5:
                if inside_diff <= -0.15:
                    score += 3.0
                elif inside_diff <= -0.05:
                    score += 2.0
                elif inside_diff >= 0.15:
                    score -= 3.0
                elif inside_diff >= 0.05:
                    score -= 2.0
        except:
            pass

        pop = parse_numeric(popularity, None)
        if pop is not None and pop >= 7 and bias.get('longshot_count', 0) >= 2:
            score += 2.0
        if pop is not None and pop <= 3 and bias.get('favorite_rate', 0.0) >= 0.70:
            score += 1.0

        return round(max(min(score * sample_factor * strength_factor, 8.0), -5.0), 1)

class BloodlineIndexMaster:
    def __init__(self, venue_path, distance_path, waku_path):
        self.venue_scores = {}
        self.distance_scores = {}
        self.waku_scores = {}
        self._load_venue_scores(venue_path)
        self._load_distance_scores(distance_path)
        self._load_waku_scores(waku_path)

    def _read_rows(self, file_path):
        if not os.path.exists(file_path):
            return []

        for enc in ['utf-8-sig', 'cp932']:
            try:
                with open(file_path, 'r', encoding=enc, errors='ignore', newline='') as f:
                    return list(csv.DictReader(f))
            except:
                continue

        return []

    def _pick(self, row, names):
        for name in names:
            value = row.get(name)
            if value not in [None, ""]:
                return str(value).strip()
        return ""

    def _to_float(self, value):
        try:
            return float(re.sub(r'[^0-9.-]', '', str(value)))
        except:
            return 0.0

    def _score_value(self, row):
        return self._to_float(self._pick(row, [
            '血統指数', '指数', 'score', 'Score', 'スコア', '加点', 'point', 'Point'
        ]))

    def _sire_value(self, row):
        return self._pick(row, ['種牡馬', '父', 'sire', 'Sire'])

    def _load_venue_scores(self, file_path):
        for row in self._read_rows(file_path):
            sire = self._sire_value(row)
            venue = self._pick(row, ['競馬場', '会場', '場所', 'basho', 'venue'])
            if sire and venue:
                self.venue_scores[(sire, venue)] = self._score_value(row)

    def _load_distance_scores(self, file_path):
        for row in self._read_rows(file_path):
            sire = self._sire_value(row)
            distance = self._pick(row, ['距離', 'distance', 'Distance'])
            distance_m = re.search(r'\d+', distance)
            if sire and distance_m:
                self.distance_scores[(sire, distance_m.group())] = self._score_value(row)

    def _load_waku_scores(self, file_path):
        for row in self._read_rows(file_path):
            sire = self._sire_value(row)
            waku = self._pick(row, ['枠', '枠番', 'waku', 'Waku'])
            waku_m = re.search(r'\d+', waku)
            if sire and waku_m:
                self.waku_scores[(sire, waku_m.group())] = self._score_value(row)

    def get_score(self, sire_name, venue, distance, waku):
        if not sire_name:
            return 0.0

        sire = sire_name.strip()
        distance_m = re.search(r'\d+', str(distance))
        waku_m = re.search(r'\d+', str(waku))

        score = self.venue_scores.get((sire, str(venue).strip()), 0.0)
        if distance_m:
            score += self.distance_scores.get((sire, distance_m.group()), 0.0)
        if waku_m:
            score += self.waku_scores.get((sire, waku_m.group()), 0.0)

        return round(score, 1)

class LapMaster:
    """改良：ラップマスターデータを管理するクラス（コース条件を厳格化）"""
    def __init__(self):
        self.master_data = defaultdict(dict)
        
    def load_venue_data(self, venue_name, file_path):
        if not os.path.exists(file_path): return
        try:
            with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    cls = row.get('クラス', '').strip()
                    age = row.get('年齢', '').strip()
                    td = row.get('TD', '').strip().replace("ダート", "ダ")
                    dist = row.get('距離', '').strip()
                    
                    # 距離やトラックが空の場合はスキップ
                    if not td or not dist: continue
                    
                    # 会場・コースを特定するため【年齢_クラス_トラック_距離】をキーにする
                    key = f"{age}_{cls}_{td}_{dist}"
                    
                    def time_to_secs(t_str):
                        if not t_str: return 999.0
                        t_str = t_str.strip()
                        parts = t_str.replace('.', ':').split(':')
                        if len(parts) == 3:
                            return float(parts[0])*60 + float(parts[1]) + float(parts[2])/100
                        elif len(parts) == 2:
                            # 1:34.2 などの形式に対応
                            return float(parts[0])*60 + float(parts[1])
                        try:
                            return float(t_str)
                        except:
                            return 999.0

                    self.master_data[venue_name][key] = {
                        'base_time': time_to_secs(row.get('基準タイム')),
                        'win_time': time_to_secs(row.get('1着タイム')),
                        'pre_5f': time_to_secs(row.get('前5F')),
                        'post_5f': time_to_secs(row.get('後5F'))
                    }
        except: pass

    def get_lap_stats(self, venue, age, cls, td, dist):
        td_clean = str(td).strip().replace("ダート", "ダ")
        dist_clean = str(dist).strip()
        key = f"{age}_{cls}_{td_clean}_{dist_clean}"
        return self.master_data.get(venue, {}).get(key, None)

current_dir = os.path.dirname(os.path.abspath(__file__))
def get_path(filename):
    p1 = os.path.join(current_dir, filename)
    p2 = os.path.join(current_dir, "..", "data", filename)
    return p1 if os.path.exists(p1) else p2


def refresh_today_track_bias_from_html():
    dairy_data_dir = os.path.abspath(os.path.join(
        current_dir,
        "..",
        "..",
        "dairy_analytics",
        "data",
    ))
    analyzer_path = os.path.join(dairy_data_dir, "analyze_today_track_bias.py")
    output_dir = os.path.join(dairy_data_dir, "output_stats", "today_track_bias")
    html_candidates = [
        os.path.join(dairy_data_dir, "今日の成績.html"),
        os.path.join(dairy_data_dir, "honnjituno.html"),
        os.path.join(dairy_data_dir, "今日の成績.htm"),
        os.path.join(current_dir, "..", "data", "今日の成績.html"),
    ]
    html_candidates = [
        os.path.abspath(path)
        for path in html_candidates
        if os.path.exists(path)
    ]

    if not os.path.exists(analyzer_path) or not html_candidates:
        return

    html_path = max(html_candidates, key=os.path.getmtime)
    summary_path = os.path.join(output_dir, "bias_summary_by_course_distance.csv")

    try:
        if (
            os.path.exists(summary_path)
            and os.path.getmtime(summary_path) >= os.path.getmtime(html_path)
        ):
            return
        subprocess.run(
            [
                sys.executable,
                analyzer_path,
                html_path,
                "--output-dir",
                output_dir,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print(f"今日の馬場傾向を更新: {html_path}")
    except Exception as exc:
        print(f"今日の馬場傾向更新をスキップ: {exc}")

VSM = VenueStatsMaster(get_path("course_stats_master.csv"))
refresh_today_track_bias_from_html()
WBM = WeeklyBiasMaster([
    get_path("過去馬場傾向_開催週指数.csv"),
    get_path("weekly_bias.csv"),
])
WEEKLY_BIAS_WEIGHT = 0.25
TODAY_BIAS_PATH = os.path.abspath(os.path.join(
    current_dir,
    "..",
    "..",
    "dairy_analytics",
    "data",
    "output_stats",
    "today_track_bias",
    "bias_summary_by_course_distance.csv"
))
TODAY_BIAS_M = TodayTrackBiasMaster(TODAY_BIAS_PATH)
TODAY_BIAS_WEIGHT = 1.0
LAP_SCORE_WEIGHT = 1.0
PSEUDO_TROUBLE_WEIGHT = 0.0
ROI_ODDS_LOW_CUT = 3.5
ROI_ODDS_HIGH_CUT = 50.0
ROI_ODDS_LOW_PENALTY = 8.0
ROI_ODDS_HIGH_PENALTY = 8.0
PREVIOUS_POPULARITY_WEAK_CUT = 7
PREVIOUS_POPULARITY_WEAK_PENALTY = 5.0
ROI_BUY_ODDS_MIN = 7.0
ROI_BUY_ODDS_MAX = 50.0
ROI_BUY_PAST3_FINISH_MIN = 6.0
ROI_BUY_PREV_ODDS_MAX = 16.0
HIST_AGARI_RANKS = {}
BLOODLINE_M = BloodlineIndexMaster(
    get_path("会場別血統指数.csv"),
    get_path("距離別血統指数.csv"),
    get_path("枠別血統指数.csv")
)
DANGER_POPULAR_SCORE_PATH = os.path.abspath(os.path.join(
    current_dir,
    "..",
    "..",
    "dairy_analytics",
    "data",
    "output_stats",
    "danger_popular",
    "danger_popular_score_table.csv"
))

# ラップマスターの初期化と全競馬場読み込み
LAP_M = LapMaster()
for v_name, f_name in VENUE_FILE_MAP.items():
    LAP_M.load_venue_data(v_name, get_path(f_name))

def normalize_jockey_name(name):
    return str(name or '').replace('．', '.').replace(' ', '').strip()


def normalize_date_key(value):
    text = str(value or '').strip().replace('.', '/').replace(' ', '')
    match = re.search(r'(\d{4})/(\d{1,2})/(\d{1,2})', text)
    if not match:
        return text
    year, month, day = match.groups()
    return f"{int(year):04d}/{int(month):02d}/{int(day):02d}"


def normalize_text_key(value):
    return str(value or '').replace(' ', '').replace('　', '').replace('*', '').strip()


class JockeyConditionStats:
    def __init__(self, file_path):
        self.stats = {}
        if not os.path.exists(file_path):
            return

        for enc in ['utf-8-sig', 'cp932']:
            try:
                with open(file_path, 'r', encoding=enc, errors='ignore', newline='') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        jockey = normalize_jockey_name(row.get('騎手'))
                        key_type = normalize_text_key(row.get('条件種別'))
                        condition = normalize_text_key(row.get('条件'))
                        if not (jockey and key_type and condition):
                            continue
                        try:
                            bonus = float(row.get('加点', 0) or 0)
                        except:
                            bonus = 0.0
                        self.stats[(jockey, key_type, condition)] = bonus
                break
            except:
                continue

    def get_bonus(self, jockey, place, track, distance, class_name):
        jockey = normalize_jockey_name(jockey)
        place = normalize_text_key(place)
        track = normalize_text_key(track).replace('ダート', 'ダ')
        distance = re.search(r'\d+', str(distance or ''))
        distance = distance.group() if distance else ''
        class_name = normalize_text_key(class_name)
        if not (jockey and track and distance):
            return 0.0

        candidates = [
            ('course', f'{place}{track}{distance}m'),
            ('classdist', f'{class_name}{track}{distance}m'),
            ('distance', f'{track}{distance}m'),
        ]
        return max(
            [self.stats.get((jockey, key_type, condition), 0.0) for key_type, condition in candidates] + [0.0]
        )


def load_current_race_conditions(yoso_path):
    conditions = {}
    if not os.path.exists(yoso_path):
        return conditions

    for enc in ['cp932', 'utf-8-sig']:
        try:
            with open(yoso_path, 'r', encoding=enc, errors='ignore', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    date = normalize_date_key(row.get('日付(yyyy.mm.dd)'))
                    place = normalize_text_key(row.get('場所'))
                    race_name = normalize_text_key(row.get('レース名'))
                    horse = normalize_text_key(row.get('馬名'))
                    if not (date and place and race_name and horse):
                        continue
                    conditions[(date, place, race_name, horse)] = {
                        'track': normalize_text_key(row.get('芝・ダ')).replace('ダート', 'ダ'),
                        'distance': normalize_text_key(row.get('距離')),
                        'class_name': normalize_text_key(row.get('クラス名')),
                        'week': detect_kaisai_week(row.get('開催')),
                    }
            break
        except:
            continue

    return conditions


def first_nonempty(row, names):
    for name in names:
        value = normalize_text_key(row.get(name, ''))
        if value:
            return value
    return ''


def normalize_surface_value(value):
    text = normalize_text_key(value).replace('ダート', 'ダ')
    if '障害' in text:
        return '障害'
    if 'ダ' in text:
        return 'ダ'
    if '芝' in text:
        return '芝'
    return text


def normalize_distance_value(value):
    match = re.search(r'\d+', str(value or ''))
    return match.group() if match else ''


def current_condition_from_upcoming_row(row):
    track = normalize_surface_value(first_nonempty(row, [
        '今回芝・ダ',
        '今回芝ダ',
        '芝・ダ',
        '芝ダ',
        '今回トラック',
        'トラック',
    ]))
    distance = normalize_distance_value(first_nonempty(row, [
        '今回距離',
        '距離',
        '今回距離m',
        '距離m',
    ]))
    class_name = first_nonempty(row, [
        '今回クラス名',
        'クラス名',
        'クラス',
    ])
    return {
        'track': track,
        'distance': distance,
        'class_name': class_name,
        'week': detect_kaisai_week(row.get('開催', row.get('今回開催', ''))),
    }


def merge_conditions(primary, fallback):
    merged = dict(fallback or {})
    for key, value in (primary or {}).items():
        if value:
            merged[key] = value
    return merged


def is_elite_transfer_source_jockey(name):
    jockey = normalize_jockey_name(name)
    return any(x in jockey for x in ['レーン', 'モレイラ', 'C.デムーロ', 'Ｃ.デムーロ', 'Cデムーロ', 'Ｃデムーロ'])


ZEN_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def hist_value(row, key, index=None, default=""):
    if isinstance(row, dict):
        return row.get(key, default)

    if index is None:
        return default

    return row[index] if len(row) > index else default


def unique_fieldnames(header):
    counts = defaultdict(int)
    names = []

    for name in header:
        counts[name] += 1
        names.append(name if counts[name] == 1 else f"{name}.{counts[name] - 1}")

    return names


def parse_hist_date(value):
    text = str(value or "").strip().replace(".", "/")
    nums = re.findall(r"\d+", text)

    if len(nums) < 3:
        return None

    try:
        return datetime(
            int(nums[0]),
            int(nums[1]),
            int(nums[2])
        )
    except:
        return None


def parse_hist_finish(value):
    text = str(value or "").translate(ZEN_DIGITS)
    match = re.search(r"\d+", text)

    return float(match.group()) if match else 99.0


def parse_race_time_seconds(value):
    text = re.sub(r"[^0-9.:]", "", str(value or ""))

    if not text:
        return 999.0

    if ":" in text:
        parts = text.split(":")
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])

    # yoso_data stores 1:59.3 as 1193, 2:22.7 as 2227.
    if text.isdigit() and len(text) >= 3:
        minutes = int(text[0])
        seconds = float(text[1:]) / 10
        return minutes * 60 + seconds

    try:
        return float(text)
    except:
        return 999.0

WEEK_MAP = {
    '1': '開幕週', '2': '開幕週',
    '3': '2週目', '4': '2週目',
    '5': '3週目', '6': '3週目',
    '7': '4週目', '8': '4週目',
    '9': '5週目', 'A': '5週目',
    'B': '最終週', 'C': '最終週',
}


def detect_kaisai_week(value):
    text = str(value or '').strip().upper()
    return WEEK_MAP.get(text[-1], '') if text else ''


def parse_numeric(value, default=0.0):
    text = str(value or '').translate(ZEN_DIGITS).replace(',', '')
    match = re.search(r'-?\d+(?:\.\d+)?', text)
    if not match:
        return default
    try:
        return float(match.group())
    except:
        return default


def current_row_odds(row):
    for key in ["今回単勝オッズ", "単勝オッズ", "オッズ"]:
        value = row.get(key)
        if value not in ["", None]:
            odds = parse_numeric(str(value).strip("()"), None)
            if odds:
                return float(odds)
    return None


def parse_hist_win_odds(value, default=None):
    raw = str(value or "").strip().replace(",", "")

    if not raw:
        return default

    in_parentheses = raw.startswith("(") and raw.endswith(")")
    num = parse_numeric(raw.strip("()"), default)

    if num is None:
        return default

    if in_parentheses:
        return float(num)

    if num >= 100:
        return float(num) / 100.0

    return float(num)


def rolling_roi_buy_context(past_rows, current_odds):
    finishes = [
        parse_hist_finish(hist_value(row, "着順", 29, ""))
        for row in past_rows[:3]
    ]
    finishes = [x for x in finishes if x < 99]

    if not finishes:
        return {
            "candidate": False,
            "reason": "過去着順不足",
        }

    past3_finish_avg = sum(finishes) / len(finishes)
    prev_odds = parse_hist_win_odds(
        hist_value(past_rows[0], "単勝配当", 37, "")
        if past_rows
        else None,
        None
    )

    past_ok = past3_finish_avg > ROI_BUY_PAST3_FINISH_MIN
    prev_odds_ok = prev_odds is not None and prev_odds <= ROI_BUY_PREV_ODDS_MAX

    odds_known = current_odds is not None
    odds_ok = (
        current_odds is not None
        and ROI_BUY_ODDS_MIN <= float(current_odds) <= ROI_BUY_ODDS_MAX
    )

    return {
        "candidate": past_ok and prev_odds_ok and (odds_ok or not odds_known),
        "odds_known": odds_known,
        "odds_ok": odds_ok,
        "past3_finish_avg": past3_finish_avg,
        "prev_odds": prev_odds,
        "reason": (
            f"過去3走平均着順{past3_finish_avg:.1f}"
            f" / 前走単勝{prev_odds:.1f}倍"
            if prev_odds is not None
            else f"過去3走平均着順{past3_finish_avg:.1f}"
        ),
    }


def get_row_value(row, key, index=None, default=''):
    return hist_value(row, key, index, default)


def get_popularity(row, default=None):
    if not isinstance(row, dict) and len(row) > 40:
        return parse_numeric(row[40], default)

    for key in ['人気', '前走人気', '単勝人気']:
        value = get_row_value(row, key, None, '')
        if value not in ['', None]:
            return parse_numeric(value, default)
    return default


def odds_value_score(current_popularity):
    return 0.0


def roi_odds_score_adjustment(odds):
    if odds is None:
        return 0.0

    try:
        odds = float(odds)
    except:
        return 0.0

    if odds < ROI_ODDS_LOW_CUT:
        return -ROI_ODDS_LOW_PENALTY

    if odds > ROI_ODDS_HIGH_CUT:
        return -ROI_ODDS_HIGH_PENALTY

    return 0.0


def previous_popularity_score_adjustment(previous_popularity):
    pop = parse_numeric(previous_popularity, None)

    if pop is None:
        return 0.0

    if pop >= PREVIOUS_POPULARITY_WEAK_CUT:
        return -PREVIOUS_POPULARITY_WEAK_PENALTY

    return 0.0


class DangerPopularScorer:
    CLASS_RANK = {
        "新馬": 0, "未勝利": 1,
        "1勝": 2, "１勝": 2, "500万": 2,
        "2勝": 3, "２勝": 3, "1000万": 3,
        "3勝": 4, "３勝": 4, "1600万": 4,
        "ｵｰﾌﾟﾝ": 5, "オープン": 5, "OP": 5,
        "Ｇ３": 6, "G3": 6, "Ｇ２": 7, "G2": 7, "Ｇ１": 8, "G1": 8,
    }

    def __init__(self, file_path):
        self.points = {}
        self.available = False
        if not os.path.exists(file_path):
            return
        for enc in ["utf-8-sig", "cp932"]:
            try:
                with open(file_path, "r", encoding=enc, errors="ignore", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if str(row.get("扱い", "")).strip() != "採用":
                            continue
                        point = parse_numeric(row.get("危険人気加点"), 0.0)
                        if point == 0:
                            continue
                        condition = str(row.get("条件", "")).strip()
                        category = str(row.get("区分", "")).strip()
                        if condition and category:
                            self.points[(condition, category)] = point
                self.available = bool(self.points)
                break
            except:
                continue

    def current_popularity(self, row):
        for key in ["今回人気", "人気", "単勝人気"]:
            value = row.get(key)
            if value not in ["", None]:
                pop = parse_numeric(value, None)
                if pop:
                    return int(pop)
        return None

    def current_odds(self, row):
        for key in ["今回単勝オッズ", "単勝オッズ", "オッズ"]:
            value = row.get(key)
            if value not in ["", None]:
                odds = parse_numeric(str(value).strip("()"), None)
                if odds:
                    return float(odds)
        return None

    def class_rank(self, value):
        text = str(value or "")
        for key, rank in self.CLASS_RANK.items():
            if key in text:
                return rank
        return None

    def odds_band(self, odds):
        if odds is None:
            return "不明"
        bins = [
            (0, 1.5, "1.0-1.4"), (1.5, 2.0, "1.5-1.9"),
            (2.0, 3.0, "2.0-2.9"), (3.0, 5.0, "3.0-4.9"),
            (5.0, 8.0, "5.0-7.9"), (8.0, 12.0, "8.0-11.9"),
            (12.0, 20.0, "12.0-19.9"), (20.0, None, "20.0以上"),
        ]
        for lo, hi, label in bins:
            if odds >= lo and (hi is None or odds < hi):
                return label
        return "不明"

    def popularity_band(self, pop):
        if pop is None:
            return "不明"
        pop = int(pop)
        if pop <= 3:
            return f"{pop}人気"
        if pop <= 5:
            return "4-5人気"
        if pop <= 9:
            return "6-9人気"
        return "10人気以下"

    def finish_band(self, finish):
        if finish is None:
            return "不明"
        finish = int(finish)
        if finish == 1:
            return "1着"
        if finish <= 3:
            return "2-3着"
        if finish <= 5:
            return "4-5着"
        if finish <= 9:
            return "6-9着"
        return "10着以下"

    def pop_diff_band(self, prev_pop, cur_pop):
        if prev_pop is None or cur_pop is None:
            return "不明"
        diff = prev_pop - cur_pop
        if diff <= -3:
            return "今回人気下降3以上"
        if diff <= -1:
            return "今回人気下降1-2"
        if diff == 0:
            return "同じ"
        if diff <= 2:
            return "今回人気上昇1-2"
        return "今回人気上昇3以上"

    def finish_pop_gap_band(self, prev_finish, prev_pop):
        if prev_finish is None or prev_pop is None:
            return "不明"
        diff = prev_finish - prev_pop
        if diff <= -3:
            return "人気以上に好走"
        if diff <= -1:
            return "やや好走"
        if diff == 0:
            return "人気通り"
        if diff <= 2:
            return "やや凡走"
        return "大きく凡走"

    def distance_change(self, cur, prev):
        if cur is None or prev is None:
            return "不明"
        diff = cur - prev
        if diff >= 200:
            return "距離延長"
        if diff <= -200:
            return "距離短縮"
        return "同距離"

    def distance_category(self, dist):
        if dist is None:
            return "不明"
        dist = int(dist)
        if dist <= 1400:
            return "短距離"
        if dist <= 1800:
            return "マイル"
        if dist <= 2200:
            return "中距離"
        return "長距離"

    def class_change(self, cur, prev):
        if cur is None or prev is None:
            return "不明"
        if cur > prev:
            return "昇級"
        if cur < prev:
            return "降級"
        return "同級"

    def interval_band(self, days):
        if days is None:
            return "不明"
        if days <= 14:
            return "中1-2週"
        if days <= 35:
            return "中3-5週"
        if days <= 70:
            return "中6-10週"
        if days <= 180:
            return "休み明け"
        return "長期休養明け"

    def frame_band(self, frame):
        if frame is None:
            return "不明"
        frame = int(frame)
        if frame <= 2:
            return "1-2枠"
        if frame <= 4:
            return "3-4枠"
        if frame <= 6:
            return "5-6枠"
        return "7-8枠"

    def score(self, current_row, past_rows, race_date, place, current_track, current_dist, current_class):
        if not self.available:
            return None

        cur_pop = self.current_popularity(current_row)
        if cur_pop is None or cur_pop < 1 or cur_pop > 3:
            return None

        prev = past_rows[0] if past_rows else None
        prev_pop = get_popularity(prev, None) if prev else None
        prev_finish = parse_numeric(hist_value(prev, "着順", 29, ""), None) if prev else None
        prev_dist = parse_numeric(hist_value(prev, "距離", 11, ""), None) if prev else None
        prev_class = self.class_rank(hist_value(prev, "クラス名", 4, "")) if prev else None
        prev_date = parse_hist_date(hist_value(prev, "日付(yyyy.mm.dd)", 0, "")) if prev else None
        interval = (race_date - prev_date).days if race_date and prev_date else None
        cur_dist = parse_numeric(current_dist, None)
        cur_class = self.class_rank(current_class)
        cur_frame = parse_numeric(current_row.get("今回枠番"), None)
        cur_odds = self.current_odds(current_row)
        style = str(hist_value(prev, "脚質", 17, "不明") if prev else "不明").strip() or "不明"
        surface = str(current_track or "").replace("ダート", "ダ").strip() or "不明"

        features = {
            "今回人気": f"{cur_pop}人気",
            "単勝オッズ帯": self.odds_band(cur_odds),
            "前走人気": self.popularity_band(prev_pop),
            "前走着順": self.finish_band(prev_finish),
            "前走人気と今回人気の差": self.pop_diff_band(prev_pop, cur_pop),
            "前走着順と前走人気の差": self.finish_pop_gap_band(prev_finish, prev_pop),
            "距離延長/短縮/同距離": self.distance_change(cur_dist, prev_dist),
            "脚質": style,
            "クラス変化": self.class_change(cur_class, prev_class),
            "レース間隔": self.interval_band(interval),
            "枠順": self.frame_band(cur_frame),
            "競馬場": str(place or "").strip(),
            "芝ダート": surface,
            "距離カテゴリ": self.distance_category(cur_dist),
        }

        total = 0
        reasons = []
        for condition, category in features.items():
            point = self.points.get((condition, category), 0)
            total += point
            if point > 0:
                reasons.append(f"{condition}:{category}+{point:g}")

        cut_note = ""
        if cur_odds is not None:
            odds_band = self.odds_band(cur_odds)
            if odds_band in {"5.0-7.9", "8.0-11.9", "12.0-19.9"}:
                cut_note = f"{cur_pop}人気・単勝{odds_band}は切り候補"
            elif cur_pop == 3:
                cut_note = "3人気は危険寄り。単勝5.0-19.9倍なら切り候補"
        elif cur_pop == 3:
            cut_note = "3人気は単勝5.0-19.9倍なら切り候補"
        else:
            cut_note = f"{cur_pop}人気は単勝5.0-19.9倍なら切り候補"

        return {
            "score": round(total, 1),
            "popularity": cur_pop,
            "odds": cur_odds,
            "reasons": reasons[:3],
            "cut_note": cut_note,
        }

    def score_from_context(self, current_popularity, past_rows, race_date, place, waku, current_track, current_dist, current_class):
        return self.score(
            {
                "今回人気": current_popularity,
                "今回枠番": waku,
            },
            past_rows,
            race_date,
            place,
            current_track,
            current_dist,
            current_class,
        )


DANGER_POPULAR_SCORER = DangerPopularScorer(DANGER_POPULAR_SCORE_PATH)


def value_index_score(past_rows, current_popularity):
    return 0.0


def pseudo_trouble_score(row, pace_info, current_track, current_dist, field_size=16):
    rank = parse_numeric(get_row_value(row, '着順', 29, 99), 99)
    diff = abs(parse_numeric(get_row_value(row, '着差', 14, 9.9), 9.9))
    corner4 = parse_numeric(get_row_value(row, '4角', 27, 99), 99)
    style = str(get_row_value(row, '脚質', 17, ''))
    agari = parse_numeric(get_row_value(row, '上り3F', 18, 99), 99)
    past_track = str(get_row_value(row, '芝・ダ', 10, '')).replace('ダート', 'ダ')
    past_dist = parse_numeric(get_row_value(row, '距離', 11, 0), 0)
    current_dist = parse_numeric(current_dist, 0)

    if rank >= 10 and not (agari > 0 and diff <= 0.8):
        return 0.0
    if diff >= 1.0 and not (agari > 0 and diff <= 0.8):
        return 0.0

    dist_gap = abs(past_dist - current_dist) if past_dist and current_dist else 9999
    if dist_gap <= 200:
        dist_factor = 1.0
    elif dist_gap <= 400:
        dist_factor = 0.7
    elif dist_gap <= 600:
        dist_factor = 0.4
    else:
        dist_factor = 0.0

    track_factor = 1.0 if past_track == str(current_track).replace('ダート', 'ダ') else 0.5
    fast_agari = False
    if current_track in CORRELATION_DB:
        place = str(get_row_value(row, '場所', 2, '')).strip()
        if place in CORRELATION_DB[current_track]:
            fast_agari = 0 < agari <= CORRELATION_DB[current_track][place]['fast']

    score = 0.0
    if fast_agari and 4 <= rank <= 7 and diff <= 0.3:
        score += 5.0
    elif fast_agari and 4 <= rank <= 8 and diff <= 0.5:
        score += 3.0
    elif fast_agari and 4 <= rank <= 9 and diff <= 0.7:
        score += 1.5

    back_40 = corner4 >= max(1, field_size * 0.6)
    if fast_agari and back_40 and diff <= 0.5 and rank >= 3:
        score += 3.0
    if pace_info == 'HIGH' and corner4 <= 4 and diff <= 0.5 and 4 <= rank <= 8:
        score += 2.0
    if score == 0.0 and fast_agari and diff <= 0.8:
        score = 1.0

    return min(score * dist_factor * track_factor, 8.0)


def agari_fit_score(base_agari_score, weekly_agari_importance):
    return base_agari_score * min(max(float(weekly_agari_importance or 0.0), 0.0), 10.0) / 10.0


def historical_race_key(row):
    return (
        normalize_date_key(hist_value(row, '日付(yyyy.mm.dd)', 0)),
        normalize_text_key(hist_value(row, '場所', 2)),
        normalize_text_key(hist_value(row, 'Ｒ', 35)),
        normalize_text_key(hist_value(row, 'レース名', 3)),
    )


def historical_horse_key(row):
    return normalize_text_key(hist_value(row, '馬名', 5))


def build_historical_agari_ranks(rows):
    race_rows = defaultdict(list)

    for row in rows:
        race_rows[historical_race_key(row)].append(row)

    ranks = {}
    for race, members in race_rows.items():
        timed = []
        for row in members:
            agari = parse_numeric(hist_value(row, '上り3F', 18), None)
            if agari and agari > 0:
                timed.append((agari, historical_horse_key(row)))

        timed.sort(key=lambda x: x[0])
        current_rank = 0
        last_time = None
        for idx, (agari, horse) in enumerate(timed, start=1):
            if last_time is None or agari != last_time:
                current_rank = idx
                last_time = agari
            ranks[(race, horse)] = current_rank

    return ranks


def recent_form_score(past_rows):
    if not past_rows:
        return 0.0

    score = 0.0
    last_finish = parse_numeric(hist_value(past_rows[0], '着順', 29), 99)
    last_diff = abs(parse_numeric(hist_value(past_rows[0], '着差', 14), 9.9))

    if last_diff > 0.3:
        if last_finish >= 10:
            score -= 5.0 * 2.0
        elif last_finish >= 7:
            score -= 3.0 * 2.0
        elif last_finish >= 5:
            score -= 1.0 * 2.0

    if last_diff >= 1.5:
        score -= 6.0 * 1.5
    elif last_diff >= 1.0:
        score -= 4.0 * 1.5
    elif last_diff >= 0.8:
        score -= 2.0 * 1.5

    agari_ranks = []
    for row in past_rows[:3]:
        rank = HIST_AGARI_RANKS.get((historical_race_key(row), historical_horse_key(row)))
        if rank:
            agari_ranks.append(rank)

    if agari_ranks:
        avg_rank = sum(agari_ranks) / len(agari_ranks)
        if avg_rank <= 3:
            score += 5.0 * 2.0
        elif avg_rank <= 5:
            score += 3.0 * 2.0
        elif avg_rank <= 8:
            score += 1.0 * 2.0
        elif avg_rank >= 12:
            score -= 3.0 * 2.0

    return score



def auxiliary_factor_notes(past_rows, current_age, current_class, current_track, current_dist):
    notes = []
    current_dist = parse_numeric(current_dist, 0)
    current_track = str(current_track or '').replace('ダート', 'ダ')
    current_class = str(current_class or '')

    if past_rows:
        last = past_rows[0]
        last_style = str(hist_value(last, '脚質', 17, ''))
        last_dist = parse_numeric(hist_value(last, '距離', 11, 0), 0)
        if (
            current_age == 3
            and '未勝利' in current_class
            and current_dist > 0
            and last_dist > 0
            and current_dist > last_dist
            and ('逃' in last_style or '先' in last_style)
        ):
            notes.append('3歳未勝利距離延長先行')

    if 'ダ' in current_track and int(current_dist) == 1700:
        for row in past_rows:
            past_track = str(hist_value(row, '芝・ダ', 10, '')).replace('ダート', 'ダ')
            past_dist = parse_numeric(hist_value(row, '距離', 11, 0), 0)
            past_finish = parse_hist_finish(hist_value(row, '着順', 29))
            if 'ダ' in past_track and int(past_dist) == 1400 and past_finish <= 3:
                notes.append('ダ1400好走→ダ1700')
                break

    return notes


def calculate_score(past_rows, r_name, current_basho, waku, horse_age, pace_info, h2h_count, j_rate, current_kinryo, current_date_str, sire_name, current_jockey, trainer_bonus=0.0, current_week='', current_popularity=None, current_odds=None, current_previous_popularity=None):
    curr_date = parse_hist_date(current_date_str)

    if curr_date:
        past_rows = [
            row for row in past_rows
            if parse_hist_date(hist_value(row, "日付(yyyy.mm.dd)", 0)) is not None
            and parse_hist_date(hist_value(row, "日付(yyyy.mm.dd)", 0)) < curr_date
        ]

    total_score = 40.0 
    track = "芝" if "芝" in r_name else "ダート"
    dist_m = re.search(r'\d+', r_name)
    dist = dist_m.group() if dist_m else ""
    course_key = f"{current_basho}{track.replace('ダート', 'ダ')}{dist}m"
    current_rot = ROTATION_MAP.get(current_basho, "")

    # yoso_data.csv全出走馬ベースの過去検証と条件を合わせるため血統加点は使わない
    total_score += 0.0

    # 2. 開催バイアス
    latest_style = str(past_rows[0][17]) if past_rows and len(past_rows[0]) > 17 else ""
    weekly_bias = WBM.get_bias(current_basho, track, current_week)
    weekly_agari_importance = weekly_bias.get('agari', 0.0) if weekly_bias else 0.0
    total_score += WBM.get_score(
        current_basho,
        track,
        waku,
        latest_style,
        current_week
    ) * WEEKLY_BIAS_WEIGHT
    total_score += TODAY_BIAS_M.get_score(
        current_basho,
        track,
        dist,
        waku,
        latest_style,
        current_popularity
    ) * TODAY_BIAS_WEIGHT

    # 3. 統計・対決・年齢
    if course_key in VSM.stats and str(waku).isdigit():
        if int(waku) in VSM.stats[course_key]["good_waku"]: total_score += 6.0
    
    total_score += min(h2h_count * 2.0, 5.0) 

    if horse_age == 6: total_score -= 5.0
    elif horse_age == 7: total_score -= 8.0
    elif horse_age >= 8: total_score -= 12.0

    # 4. 騎手加点
    if j_rate is not None:
        if j_rate >= 40.0: total_score += 3.0
        elif j_rate >= 25.0: total_score += 2.0
        elif j_rate >= 15.0: total_score += 1.0

    try:
        total_score += min(max(float(trainer_bonus), 0.0), 3.0)
    except:
        pass
    total_score += min(value_index_score(past_rows, current_popularity), 3.0)

    if past_rows and len(past_rows[0]) > 8:
        last_jockey = past_rows[0][8]
        if (
            is_elite_transfer_source_jockey(last_jockey)
            and normalize_jockey_name(last_jockey) != normalize_jockey_name(current_jockey)
        ):
            total_score -= 2.0

    # 5. 斤量ロジック
    def clean_kinryo(val):
        return float(re.sub(r'[^0-9.]', '', str(val)) or 0)

    try:
        cur_kin = clean_kinryo(current_kinryo)
        if past_rows and len(past_rows[0]) > 9:
            last_kin = clean_kinryo(past_rows[0][9])
            diff = cur_kin - last_kin
            if diff <= -2.0: total_score += 3.0
            elif diff >= 2.0: total_score -= 2.0
        if cur_kin >= 58.0: total_score -= 3.0
    except: pass

    # 6. 全履歴スキャン
    if past_rows:
        try:
            last_date = parse_hist_date(hist_value(past_rows[0], "日付(yyyy.mm.dd)", 0))
            weeks_out = (curr_date - last_date).days / 7
            if weeks_out >= 9:
                if horse_age == 5: total_score -= 4.0
                elif horse_age == 6: total_score -= 7.0
                elif horse_age >= 7: total_score -= 20.0
        except: pass

        has_rot_win = False
        is_g1_winner = False
        is_classic_winner = False
        lap_score_total = 0.0
        diff_t_score_total = 0.0
        agari_fit_total = 0.0
        pseudo_trouble_total = 0.0

        for i, row in enumerate(past_rows):
            if len(row) < 30: continue
            try:
                p_basho = str(row[2]).strip()
                p_rank_clean = re.sub(r'[^0-9.]', '', str(row[29]))
                p_rank = float(p_rank_clean) if p_rank_clean else 99.0
                p_race_name = str(row[3])
                p_grade = str(row[4])
                
                # --- 全国ラップマスタ連動能力評価ロジック ---
                p_track = str(row[10]).strip().replace("ダート", "ダ")
                p_dist = str(row[11]).strip()
                
                p_time_raw = str(row[13]) 
                p_diff_raw = str(row[14])
                p_class = str(row[4]).strip()
                p_age = str(row[7]).strip() 

                p_secs = parse_race_time_seconds(p_time_raw)
                p_diff = float(re.sub(r'[^0-9.-]', '', p_diff_raw)) if p_diff_raw else 9.9
                
                # キーを厳格化して統計データを取得
                lap_stats = LAP_M.get_lap_stats(p_basho, p_age, p_class, p_track, p_dist)
                
                if lap_stats and p_secs < 900.0:
                    base_t = lap_stats['base_time']
                    win_t = lap_stats['win_time']
                    
                    # ① タイム偏差ファクター：過去走タイムが平均1着タイムよりどれだけ抜けて速いか
                    time_deviation = win_t - p_secs
                    if time_deviation > 0.5 and p_rank <= 3:
                        lap_score_total += min(time_deviation * 4.0, 10.0)

                    # ② 高速決着の質判定（馬場か、実力か）
                    if (base_t - p_secs) >= 0.8:
                        if p_rank == 1.0 and p_diff >= 0.4:
                            lap_score_total += 8.0 
                        elif p_diff <= 0.1:
                            lap_score_total -= 2.0
                            
                    # ③ ラップ適性判定：前半のペース（Hペース耐性があるか）
                    if pace_info == "HIGH" and lap_stats['pre_5f'] < 900.0:
                        if time_deviation > 0.2 and str(row[17]) in ["逃げ", "先行"]:
                            lap_score_total += 3.0
                # --------------------------------------------------

                if ROTATION_MAP.get(p_basho) == current_rot and p_rank <= 3:
                    has_rot_win = True
                if p_rank == 1.0:
                    if "G1" in p_grade or "Ｇ１" in p_grade: is_g1_winner = True
                    if any(c in p_race_name for c in CLASSIC_RACES): is_classic_winner = True
                
                if i < 5:
                    if track in CORRELATION_DB and p_basho in CORRELATION_DB[track]:
                        agari_c = re.sub(r'[^0-9.]', '', str(row[18]))
                        agari = float(agari_c) if agari_c else 99.0
                        if 0 < agari <= CORRELATION_DB[track][p_basho]["fast"]:
                            total_score += 4.0
                            agari_fit_total += agari_fit_score(4.0, weekly_agari_importance)

                    pseudo_trouble_total += pseudo_trouble_score(row, pace_info, track, dist, len(past_rows))
                    
                    diff_t_raw = re.sub(r'[^0-9.-]', '', str(row[14]))
                    diff_t = abs(float(diff_t_raw)) if diff_t_raw else 9.9
                    if diff_t <= (0.3 if "Ｇ" in p_grade else 0.2):
                        diff_t_score_total += 10.0
            except: continue

        if len(past_rows[0]) > 17:
            style = str(past_rows[0][17])
            if pace_info == "SLOW" and any(s in style for s in ["逃げ", "先行"]):
                lap_score_total += 3.0
            if pace_info == "HIGH" and any(s in style for s in ["差し", "追込"]):
                lap_score_total += 5.0

        total_score += min(max(lap_score_total, 0.0), 10.0) * LAP_SCORE_WEIGHT
        total_score += min(diff_t_score_total, 15.0)
        total_score += min(agari_fit_total, 5.0)
        total_score += min(pseudo_trouble_total, 8.0) * PSEUDO_TROUBLE_WEIGHT
        if has_rot_win: total_score += 2.0
        total_score = min(total_score, 100.0) + recent_form_score(past_rows)

    total_score = min(total_score, 100.0)
    total_score += roi_odds_score_adjustment(current_odds)
    total_score += previous_popularity_score_adjustment(current_previous_popularity)

    return max(0.0, min(total_score, 100.0))

def main():
    global HIST_AGARI_RANKS

    jockey_stats = defaultdict(lambda: None)
    j_path = get_path("jockey.csv")
    if os.path.exists(j_path):
        with open(j_path, 'r', encoding='cp932', errors='ignore') as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get('名前(ターゲット内表記)', '').strip()
                if not name: continue
                raw_rate = row.get('連対率', '').replace('%', '').strip()
                if raw_rate:
                    try: jockey_stats[name] = float(raw_rate)
                    except: pass

    trainer_bonuses = load_trainer_bonuses()

    horse_histories = defaultdict(list)
    all_history_rows = []
    yoso_path = get_path("yoso_data.csv")
    current_conditions = load_current_race_conditions(yoso_path)
    if os.path.exists(yoso_path):
        with open(yoso_path, 'r', encoding='cp932', errors='ignore') as f:
            reader = csv.reader(f)
            next(reader)
            for row in reader:
                if len(row) > 18:
                    horse_histories[row[5].strip()].append(row)
                    all_history_rows.append(row)

    HIST_AGARI_RANKS = build_historical_agari_ranks(all_history_rows)
    for name in horse_histories:
        horse_histories[name].sort(
            key=lambda row: parse_hist_date(hist_value(row, "日付(yyyy.mm.dd)", 0)) or datetime.min,
            reverse=True
        )

    upcoming_path = get_path("upcoming.csv") 
    if not os.path.exists(upcoming_path): return

    all_race_results = []
    with open(upcoming_path, 'r', encoding='cp932', errors='ignore') as f:
        reader = csv.DictReader(f)
        temp_races = defaultdict(list)
        for row in reader:
            raw_date = row.get('今回日付S', datetime.now().strftime('%Y/%m/%d')).replace('.', '/')
            try:
                d_obj = datetime.strptime(raw_date, '%Y/%m/%d')
                r_date = d_obj.strftime('%Y/%m/%d')
            except:
                r_date = raw_date
            race_key = (row['今回場所'], row['今回発走時刻'], row['今回レース名'], row['今回レース番号'], r_date)
            temp_races[race_key].append(row)

        for key, horses in temp_races.items():
            basho, time, r_name, r_num, r_date = key
            race_date = parse_hist_date(r_date)

            def before_race_history(name):
                return [
                    row for row in horse_histories.get(name, [])
                    if parse_hist_date(hist_value(row, "日付(yyyy.mm.dd)", 0)) is not None
                    and (
                        race_date is None
                        or parse_hist_date(hist_value(row, "日付(yyyy.mm.dd)", 0)) < race_date
                    )
                ]

            h2h_beat_counts = defaultdict(int)
            for h1 in horses:
                n1 = h1['馬名'].strip()
                beaten_opponents = set()
                for h2 in horses:
                    n2 = h2['馬名'].strip()
                    if n1 == n2: continue
                    for r1 in before_race_history(n1):
                        for r2 in before_race_history(n2):
                            if len(r1) > 29 and len(r2) > 29 and r1[0] == r2[0] and r1[2] == r2[2] and r1[3] == r2[3]:
                                try:
                                    rk1 = float(re.sub(r'[^0-9.]', '', str(r1[29])) or 99.0)
                                    rk2 = float(re.sub(r'[^0-9.]', '', str(r2[29])) or 99.0)
                                    if rk1 < rk2: beaten_opponents.add(n2)
                                except: continue
                h2h_beat_counts[n1] = len(beaten_opponents)

            styles = []
            for h in horses:
                h_name = h['馬名'].strip()
                history = before_race_history(h_name)
                styles.append(str(history[0][17]) if history and len(history[0]) > 17 else "不明")
            nige_senko = styles.count("逃げ") + styles.count("先行")
            pace = "HIGH" if nige_senko >= 6 else ("SLOW" if nige_senko <= 2 else "MID")

            race_scores = []
            debut_count = 0

            for h in horses:
                name = h['馬名'].strip()
                if not horse_histories[name]:
                    debut_count += 1

                age_s = re.search(r'\d+', str(h.get('年齢(今回時年齢)', '4')))
                age = int(age_s.group()) if age_s else 4
                
                sire = h.get('父', h.get('種牡馬', h.get('sire', '')))
                if not sire and name in horse_histories:
                    hist = before_race_history(name)
                    if len(hist) > 0 and len(hist[0]) > 17:
                        sire = str(hist[0][17])
                
                trainer_name = h.get('調教師', h.get('今回調教師', ''))
                trainer_bonus = trainer_bonuses[normalize_trainer_name(trainer_name)]

                condition = merge_conditions(
                    current_condition_from_upcoming_row(h),
                    current_conditions.get((
                        normalize_date_key(r_date),
                        normalize_text_key(basho),
                        normalize_text_key(r_name),
                        normalize_text_key(name)
                    ), {})
                )
                current_week = (
                    condition.get('week')
                    or detect_kaisai_week(h.get('開催', h.get('今回開催', '')))
                )
                current_popularity = h.get('人気', h.get('今回人気', None))
                current_odds = current_row_odds(h)
                current_previous_popularity = (
                    history[0][40]
                    if history and len(history[0]) > 40
                    else None
                )
                score_r_name = (
                    f"{condition.get('track', '')}{condition.get('distance', '')} {r_name}"
                    if condition.get('track') or condition.get('distance')
                    else r_name
                )

                score = calculate_score(
                    horse_histories[name], score_r_name, basho, h['今回枠番'], age, pace, 
                    h2h_beat_counts[name], jockey_stats[h['今回騎手'].strip()], h.get('今回斤量', 0), r_date, sire, h['今回騎手'], trainer_bonus, current_week, current_popularity, current_odds, current_previous_popularity
                )
                current_track = condition.get('track', '')
                current_dist = condition.get('distance', '')
                current_class = condition.get('class_name', '')
                notes = auxiliary_factor_notes(
                    before_race_history(name),
                    age,
                    current_class,
                    current_track,
                    current_dist
                )
                roi_buy_info = rolling_roi_buy_context(history, current_odds)
                race_scores.append({
                    'name': name,
                    'score': score,
                    'jockey': h['今回騎手'],
                    'num': h.get('今回馬番', '?'),
                    'notes': notes,
                    'current_odds': current_odds,
                    'roi_buy_info': roi_buy_info,
                })
            
            sorted_h = sorted(race_scores, key=lambda x: x['score'], reverse=True)
            for rank, horse in enumerate(sorted_h, start=1):
                info = horse.get('roi_buy_info') or {}
                horse['roi_buy_flag'] = bool(info.get('candidate') and rank <= 2)
                horse['roi_buy_rank'] = rank
            diff = (sorted_h[0]['score'] - sorted_h[1]['score']) if len(sorted_h) >= 2 else 0
            
            # 出力用に date (r_date) を結果データに追加
            all_race_results.append({
                'basho': basho, 'time': time, 'title': f"{r_num}R {r_name}", 
                'pace': pace, 'horses': sorted_h, 'diff': diff, 'date': r_date,
                'debut_count': debut_count
            })

    # 1. すべての会場をリストアップしてソート（会場名でソート）
    all_bashos = sorted(list(set(r['basho'] for r in all_race_results)))
    
    for basho in all_bashos:
        # 2. 会場ごとに全レースを抽出
        basho_races = [x for x in all_race_results if x['basho'] == basho]
        
        # 3. 日付 -> レース番号の順でソートする関数
        def sort_key(r):
            # タイトルからレース番号(数字)を抽出
            match = re.search(r'(\d+)R', r['title'])
            race_num = int(match.group(1)) if match else 99
            # 日付文字列とレース番号をタプルにして返す
            return (r['date'], race_num)
            
        sorted_races = sorted(basho_races, key=sort_key)
        basho_lines = [f"\n==================== {basho}開催 ===================="]
        basho_has_star = False
        
        # 4. 出力
        for r in sorted_races:
            debut_mark = (
                " !!! 初出走3頭以上"
                if r.get('debut_count', 0) >= 3
                else ""
            )

            race_lines = [
                f"\n▼ 【{r['date']}】 {r['time']} {r['basho']} {r['title']} ({r['pace']}){debut_mark}"
            ]
            race_has_star = False

            top_score = r["horses"][0].get("score", 0) if r.get("horses") else 0
            top_odds = r["horses"][0].get("current_odds") if r.get("horses") else None
            score_diff_buy = (
                top_score > 75
                and 10 <= r["diff"] < 15
                and (top_odds is None or top_odds >= 6.0)
            )
            if score_diff_buy:
                race_has_star = True
                odds_note = (
                    f"単勝{top_odds:.1f}倍"
                    if top_odds is not None
                    else "単勝6倍以上なら"
                )
                race_lines.append(
                    f"★ score差(1位-2位): {r['diff']:+.1f} "
                    f"/ {odds_note} ★"
                )

            if len(r["horses"]) >= 3:
                diff_12 = r["horses"][0]["score"] - r["horses"][1]["score"]
                diff_23 = r["horses"][1]["score"] - r["horses"][2]["score"]
                if diff_12 <= 2 and diff_23 >= 10:
                    race_has_star = True
                    race_lines.append(
                        f"★★★ 1位-2位差: {diff_12:+.1f} / "
                        f"2位-3位差: {diff_23:+.1f} / おすすめ: ワイド1-2位 ★★★"
                    )

            score80_odds6_targets = []
            for h in r["horses"]:
                if h.get("score", 0) < 80:
                    continue
                odds = h.get("current_odds")
                if odds is not None and odds < 6.0:
                    continue
                score80_odds6_targets.append(h)

            if score80_odds6_targets:
                race_has_star = True
                names = []
                for h in score80_odds6_targets:
                    odds = h.get("current_odds")
                    odds_text = (
                        f"単勝{odds:.1f}倍"
                        if odds is not None
                        else "単勝オッズ6倍以上なら"
                    )
                    names.append(
                        f"{h['name']}({h.get('score', 0):.1f}点/{odds_text})"
                    )
                race_lines.append(f"★★★★★ score80以上 + 単勝オッズ6倍以上: {' / '.join(names)} ★★★★★")
             
            for i, h in enumerate(r['horses']):
                tag = f"({i+1}番手)  "
                notes = h.get('notes') or []
                note_text = f" [補助: {' / '.join(notes)}]" if notes else ""
                race_lines.append(f"  {tag} {h['score']:>5.1f}点 : {h['name']:<14} (馬番:{h['num']}){note_text}")

            basho_has_star = basho_has_star or race_has_star
            for line in race_lines:
                show_in_terminal = race_has_star
                horse_rank_match = re.match(r"\s+\((\d+)番手\)", str(line))
                if horse_rank_match and int(horse_rank_match.group(1)) > 11:
                    show_in_terminal = False
                basho_lines.append((line, show_in_terminal))

        for item in basho_lines:
            if isinstance(item, tuple):
                line, race_has_star = item
            else:
                line, race_has_star = item, basho_has_star
            log(line, to_terminal=race_has_star)
# --- 追加する関数 ---
def update_and_report(all_race_results):
    import json
    log_file = "analysis_history.json"
    
    # 既存の履歴を読み込み
    history = []
    if os.path.exists(log_file):
        with open(log_file, 'r', encoding='utf-8') as f:
            try: history = json.load(f)
            except: history = []

    # 今回の結果を追記
    for race in all_race_results:
        history.append({
            "date": race['date'],
            "basho": race['basho'],
            "title": race['title'],
            "horses": [{"name": h['name'], "score": h['score']} for h in race['horses']],
            "diff": race['diff']
        })

    with open(log_file, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=4)

    print("\n" + "="*80)
    print("📊 競馬アナリティクス 総合レポート")
    print("="*80)
    print(f"集計完了：{len(history)}レース分のデータが analysis_history.json に蓄積されました。")
# --------------------

HIGH_ROI_COURSE_BIAS_KEYS = {
    "TOKYO_T1400",
    "FUKUSHIMA_D1700",
    "FUKUSHIMA_D1150",
    "KYOTO_T1400",
    "KYOTO_T2000",
    "TOKYO_T1800",
    "KYOTO_D1200",
    "NAKAYAMA_T1800",
    "TOKYO_T1600",
    "KYOTO_D1400",
    "KOKURA_T1200",
    "HANSHIN_D1400",
    "KYOTO_T1600",
    "NAKAYAMA_T2200",
    "TOKYO_D1600",
    "NIIGATA_T1400",
    "NAKAYAMA_T1200",
    "HANSHIN_T1600",
    "KOKURA_D1700",
}


def run_and_append_course_bias_candidates():
    script_path = os.path.join(current_dir, "upcoming_course_bias_candidates.py")
    data_dir = os.path.abspath(os.path.join(current_dir, "..", "data"))
    out_dir = os.path.join(data_dir, "course_bias_candidates")
    candidates_path = os.path.join(
        out_dir,
        "upcoming_top_bias_odds7_or_unknown_candidates.csv"
    )
    all_path = os.path.join(out_dir, "upcoming_course_bias_all.csv")

    if not os.path.exists(script_path):
        log("\n▼ コースバイアス候補まとめ")
        log("upcoming_course_bias_candidates.py が見つかりません。")
        return

    try:
        subprocess.run(
            [sys.executable, script_path],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        log("\n▼ コースバイアス候補まとめ")
        log(f"候補作成をスキップ: {exc}")
        return

    rows = []
    if os.path.exists(candidates_path):
        with open(candidates_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
            rows = list(csv.DictReader(f))

    all_rows = []
    if os.path.exists(all_path):
        with open(all_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
            all_rows = list(csv.DictReader(f))

    no_info = sum(1 for row in all_rows if row.get("判定可否") == "NO_COURSE_INFO")
    no_table = sum(1 for row in all_rows if row.get("判定可否") == "NO_TABLE")
    ok_count = sum(1 for row in all_rows if row.get("判定可否") == "OK")

    printable_rows = [
        row for row in rows
        if str(row.get("course_key", "")).strip() in HIGH_ROI_COURSE_BIAS_KEYS
    ]

    log("\n▼ コースバイアス候補まとめ")
    log(
        f"判定OK:{ok_count} / コース情報不足:{no_info} / テーブルなし:{no_table} "
        f"/ 候補:{len(rows)} / 表示対象:{len(printable_rows)}"
    )

    place_summary_path = os.path.abspath(os.path.join(
        current_dir,
        "..",
        "..",
        "dairy_analytics",
        "data",
        "output_stats",
        "pre_race_course_distance_bias_roi",
        "pre_race_2025plus_course_bias_candidate_place_summary.csv",
    ))
    if os.path.exists(place_summary_path):
        try:
            with open(place_summary_path, "r", encoding="utf-8-sig", errors="ignore", newline="") as f:
                for summary_row in csv.DictReader(f):
                    if summary_row.get("strategy") != "top_bias_odds7":
                        continue
                    bets = parse_numeric(summary_row.get("bets"), 0) or 0
                    hits = parse_numeric(summary_row.get("place_hits"), 0) or 0
                    place_rate = parse_numeric(summary_row.get("place_rate"), 0) or 0
                    win_rate = parse_numeric(summary_row.get("win_rate"), 0) or 0
                    avg_odds = parse_numeric(summary_row.get("avg_odds"), 0) or 0
                    log(
                        "過去検証(2025年以降): "
                        f"単勝7倍以上なら複勝率{place_rate:.2f}% "
                        f"({int(hits)}/{int(bets)}) / 勝率{win_rate:.2f}% / 平均単勝{avg_odds:.2f}倍"
                    )
                    break
        except Exception as exc:
            log(f"複勝率の読み込みをスキップ: {exc}")
    else:
        log("過去検証(2025年以降): 複勝率データ未作成")

    if not printable_rows:
        log("高回収率コース該当候補なし")
        return

    def sort_key(row):
        date = row.get("日付", "")
        place = row.get("場所", "")
        race = parse_numeric(row.get("R"), 99) or 99
        score = parse_numeric(row.get("pre_race_bias_score"), 0) or 0
        return (date, place, race, -score)

    for row in sorted(printable_rows, key=sort_key):
        log(
            f"{row.get('日付')} {row.get('場所')} {row.get('R')}R "
            f"{row.get('馬名')} "
            f"bias:{row.get('pre_race_bias_score')} "
            f"単勝7倍以上なら "
            f"{row.get('course_key', '')} "
            f"{row.get('推定脚質', '')}/{row.get('推定位置', '')}"
        )


def save_predictions_to_dairy_analytics(output_label=None):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prediction_dir_parts = [
        current_dir,
        "..",
        "..",
        "dairy_analytics",
        "data",
        "predictions"
    ]
    if output_label:
        prediction_dir_parts.append(output_label)

    prediction_dir = os.path.abspath(os.path.join(*prediction_dir_parts))
    os.makedirs(prediction_dir, exist_ok=True)

    race_dates = []

    for line in output_lines:
        match = re.search(r"【(\d{4})/(\d{1,2})/(\d{1,2})】", str(line))

        if not match:
            continue

        year, month, day = match.groups()
        race_dates.append(f"{year}{month.zfill(2)}{day.zfill(2)}")

    unique_dates = sorted(set(race_dates))

    if len(unique_dates) == 1:
        file_name = f"{unique_dates[0]}.txt"
    elif len(unique_dates) >= 2:
        file_name = f"{unique_dates[0]}-{unique_dates[-1]}.txt"
    else:
        file_name = datetime.now().strftime("%Y%m%d_%H%M%S.txt")

    save_path = os.path.join(prediction_dir, file_name)
    if os.path.exists(save_path):
        base, ext = os.path.splitext(save_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = f"{base}_{timestamp}{ext}"
        counter = 2
        while os.path.exists(save_path):
            save_path = f"{base}_{timestamp}_{counter}{ext}"
            counter += 1

    with open(save_path, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(output_lines))

    print()
    print("予想保存完了")
    print(save_path)


if __name__ == "__main__":
    main()
    run_and_append_course_bias_candidates()
    save_predictions_to_dairy_analytics()

