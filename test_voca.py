"""Tests for voca.py"""

import json
import os
import sys
import pytest
from unittest.mock import MagicMock, patch
import requests

# ── Bootstrap import ──────────────────────────────────────────────────────────
# voca parses sys.argv and runs top-level code at import time.
# Use --query 1 (numeric show-ID query) so startup makes one mocked API call
# (get_show_data) and exits cleanly without touching the filesystem.

_SHOW_DATA = {
    'id': 1, 'name': 'Test Show', 'language': 'English',
    'genres': ['Drama'], 'premiered': '2000-01-01',
    'network': {'name': 'Test Network', 'country': {'name': 'USA'}},
    'summary': '<p>A <b>test</b> show.</p>',
}


def _mock_session(payload):
    s = MagicMock()
    r = MagicMock()
    r.raise_for_status.return_value = None
    r.json.return_value = payload
    s.get.return_value = r
    return s


with patch.object(sys, 'argv', ['voca.py', '--query', '1']), \
        patch('requests.Session', return_value=_mock_session(_SHOW_DATA)):
    import voca


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_globals():
    """Restore mutated module-level globals after every test."""
    saved = {k: getattr(voca, k) for k in (
        'appendees', 'jumbled', 'preview', 'filetype', 'enable_backup_log',
    )}
    had_appender = hasattr(voca, 'appender')
    saved_appender = getattr(voca, 'appender', None)
    yield
    for k, v in saved.items():
        setattr(voca, k, v)
    if had_appender:
        voca.appender = saved_appender
    elif hasattr(voca, 'appender'):
        del voca.appender
    voca._episode_cache.clear()


@pytest.fixture()
def tmp_log(tmp_path):
    """Redirect log file to a temporary location."""
    log_dir = tmp_path / 'log'
    log_file = log_dir / 'latest.json'
    with patch.object(voca, 'LOG_DIR', str(log_dir)), \
            patch.object(voca, 'LOG_FILE', str(log_file)):
        yield log_dir, log_file


@pytest.fixture()
def restore_cwd():
    orig = os.getcwd()
    yield
    os.chdir(orig)


# ── make_filesafe ─────────────────────────────────────────────────────────────

class TestMakeFilesafe:
    def test_normal_string_unchanged(self):
        assert voca.make_filesafe('Hello World') == 'Hello World'

    @pytest.mark.parametrize('ch', list(r'\/:*?"<>|'))
    def test_forbidden_char_replaced(self, ch):
        assert voca.make_filesafe(f'a{ch}b') == 'a_b'

    def test_strips_leading_trailing_spaces_and_dots(self):
        assert voca.make_filesafe('  Hello  ') == 'Hello'
        assert voca.make_filesafe('...Hello...') == 'Hello'
        assert voca.make_filesafe(' .Hello. ') == 'Hello'

    def test_nul_character_dropped(self):
        assert voca.make_filesafe('a\x00b') == 'ab'

    def test_whitespace_control_char_collapsed_to_space(self):
        # \x1f is treated as whitespace by str.split(), so it becomes a space
        assert voca.make_filesafe('a\x1fb') == 'a b'

    def test_collapses_internal_whitespace(self):
        assert voca.make_filesafe('Hello   World') == 'Hello World'

    def test_empty_string_returns_untitled(self):
        assert voca.make_filesafe('') == 'Untitled'

    def test_none_returns_untitled(self):
        assert voca.make_filesafe(None) == 'Untitled'

    def test_only_stripped_chars_returns_untitled(self):
        assert voca.make_filesafe('...') == 'Untitled'
        assert voca.make_filesafe('   ') == 'Untitled'

    def test_max_length_enforced(self):
        assert len(voca.make_filesafe('a' * 300)) <= 240

    def test_exactly_max_length_not_truncated(self):
        assert len(voca.make_filesafe('a' * 240)) == 240

    def test_unicode_preserved(self):
        assert voca.make_filesafe('Héllo Wörld') == 'Héllo Wörld'

    def test_custom_replacement_char(self):
        assert voca.make_filesafe('a/b', replacement='-') == 'a-b'


# ── weed_files ────────────────────────────────────────────────────────────────

class TestWeedFiles:
    def test_specific_ext_all_match(self):
        files = ['a.mkv', 'b.mkv']
        result, ext = voca.weed_files(files[:], '.mkv')
        assert set(result) == {'a.mkv', 'b.mkv'}
        assert ext == '.mkv'

    def test_specific_ext_filters_non_matching(self, capsys):
        result, ext = voca.weed_files(['a.mkv', 'b.mp4', 'c.mkv'], '.mkv')
        assert set(result) == {'a.mkv', 'c.mkv'}
        assert 'b.mp4' in capsys.readouterr().out

    def test_auto_detect_single_ext(self):
        result, ext = voca.weed_files(['a.mkv', 'b.mkv'], None)
        assert set(result) == {'a.mkv', 'b.mkv'}
        assert ext == '.mkv'

    def test_auto_detect_mixed_ext_returns_none(self):
        result, ext = voca.weed_files(['a.mkv', 'b.mp4'], None)
        assert set(result) == {'a.mkv', 'b.mp4'}
        assert ext is None

    def test_auto_detect_no_video_files(self):
        result, ext = voca.weed_files(['cover.jpg', 'notes.txt'], None)
        assert result == [] and ext is None

    def test_empty_list(self):
        result, ext = voca.weed_files([], None)
        assert result == [] and ext is None

    def test_srt_files_accepted(self):
        result, ext = voca.weed_files(['a.srt', 'b.srt'], None)
        assert set(result) == {'a.srt', 'b.srt'}
        assert ext == '.srt'

    def test_non_video_silently_excluded(self):
        result, ext = voca.weed_files(['a.mkv', 'cover.jpg', 'b.mkv'], None)
        assert set(result) == {'a.mkv', 'b.mkv'}

    def test_all_video_types_accepted(self):
        files = ['a.mkv', 'b.mp4', 'c.avi']
        result, ext = voca.weed_files(files[:], None)
        assert set(result) == set(files)
        assert ext is None  # mixed


# ── weed_folders ──────────────────────────────────────────────────────────────

class TestWeedFolders:
    def test_output_is_sorted(self):
        assert voca.weed_folders(['S03', 'S01', 'S02']) == ['S01', 'S02', 'S03']

    def test_extras_excluded(self):
        assert 'Extras' not in voca.weed_folders(['Season 01', 'Extras'])

    def test_subs_excluded(self):
        assert 'Subs' not in voca.weed_folders(['Season 01', 'Subs'])

    def test_case_insensitive(self):
        assert voca.weed_folders(['Season 01', 'EXTRAS', 'SUBS']) == ['Season 01']

    def test_partial_name_match_excluded(self):
        result = voca.weed_folders(['Season 01', 'Season 02 Extras'])
        assert 'Season 02 Extras' not in result

    def test_empty_list(self):
        assert voca.weed_folders([]) == []


# ── get_filenames ─────────────────────────────────────────────────────────────

class TestGetFilenames:
    def test_basic_numbering_and_extension(self):
        assert voca.get_filenames(['Pilot', 'Second'], '.mkv') == \
            ['01 Pilot.mkv', '02 Second.mkv']

    def test_zero_pads_two_digits(self):
        titles = [f'Ep {i}' for i in range(1, 12)]
        result = voca.get_filenames(titles, '.mkv')
        assert result[0].startswith('01 ')
        assert result[9].startswith('10 ')
        assert result[10].startswith('11 ')

    def test_mixed_filetype_preserves_each_extension(self):
        result = voca.get_filenames(['Pilot', 'Second'], None,
                                    old_names=['ep1.mkv', 'ep2.mp4'])
        assert result[0].endswith('.mkv')
        assert result[1].endswith('.mp4')

    def test_forbidden_chars_sanitized_in_title(self):
        result = voca.get_filenames(['Hello/World', 'Test: Ep'], '.mkv')
        assert '/' not in result[0]
        assert ':' not in result[1]

    def test_empty_list(self):
        assert voca.get_filenames([], '.mkv') == []

    def test_append_feature(self):
        voca.appendees = '2'
        voca.appender = ' (Extended)'
        result = voca.get_filenames(['Pilot', 'Second'], '.mkv')
        assert result[0] == '01 Pilot.mkv'
        assert result[1] == '02 Second (Extended).mkv'

    def test_append_multiple_episodes(self):
        voca.appendees = '1,3'
        voca.appender = ' (Director\'s Cut)'
        result = voca.get_filenames(['One', 'Two', 'Three'], '.mkv')
        assert result[0].endswith(" (Director's Cut).mkv")
        assert result[1] == '02 Two.mkv'
        assert result[2].endswith(" (Director's Cut).mkv")


# ── safe_rename ───────────────────────────────────────────────────────────────

class TestSafeRename:
    def test_successful_rename(self, tmp_path):
        src = tmp_path / 'old.mkv'
        src.write_text('x')
        dst = tmp_path / 'new.mkv'
        assert voca.safe_rename(str(src), str(dst)) is True
        assert dst.exists() and not src.exists()

    def test_refuses_to_overwrite_existing_file(self, tmp_path, capsys):
        src = tmp_path / 'old.mkv'
        src.write_text('x')
        dst = tmp_path / 'existing.mkv'
        dst.write_text('original')
        assert voca.safe_rename(str(src), str(dst)) is False
        assert src.exists()
        assert dst.read_text() == 'original'
        assert 'Error' in capsys.readouterr().out


# ── rename ────────────────────────────────────────────────────────────────────

class TestRename:
    @pytest.fixture(autouse=True)
    def _restore(self, restore_cwd):
        pass

    def test_successful_rename(self, tmp_path):
        for f in ['ep01.mkv', 'ep02.mkv']:
            (tmp_path / f).write_text('x')
        voca.preview = False
        os.chdir(tmp_path)
        result = voca.rename(['ep01.mkv', 'ep02.mkv'],
                             ['01 Pilot.mkv', '02 Second.mkv'], False, [], [])
        assert result is False
        assert (tmp_path / '01 Pilot.mkv').exists()
        assert (tmp_path / '02 Second.mkv').exists()

    def test_unchanged_file_prints_unchanged(self, tmp_path, capsys):
        (tmp_path / '01 Pilot.mkv').write_text('x')
        voca.preview = False
        os.chdir(tmp_path)
        voca.rename(['01 Pilot.mkv'], ['01 Pilot.mkv'], False, [], [])
        assert 'unchanged' in capsys.readouterr().out

    def test_more_files_than_episodes_returns_1(self):
        result = voca.rename(['a.mkv', 'b.mkv'], ['01 Ep.mkv'], False, [], [])
        assert result == 1

    def test_fewer_files_than_episodes_returns_2(self):
        result = voca.rename(['a.mkv'], ['01.mkv', '02.mkv'], False, [], [])
        assert result == 2

    def test_refuses_overwrite_returns_3(self, tmp_path):
        (tmp_path / 'ep01.mkv').write_text('x')
        (tmp_path / 'existing.mkv').write_text('y')
        voca.preview = False
        os.chdir(tmp_path)
        result = voca.rename(['ep01.mkv'], ['existing.mkv'], False, [], [])
        assert result == 3
        assert (tmp_path / 'ep01.mkv').exists()

    def test_preview_mode_makes_no_changes(self, tmp_path):
        (tmp_path / 'ep01.mkv').write_text('x')
        voca.preview = True
        os.chdir(tmp_path)
        voca.rename(['ep01.mkv'], ['01 Pilot.mkv'], False, [], [])
        assert (tmp_path / 'ep01.mkv').exists()
        assert not (tmp_path / '01 Pilot.mkv').exists()

    def test_subtitle_rename(self, tmp_path):
        (tmp_path / 'ep01.mkv').write_text('x')
        subs = tmp_path / 'subs'
        subs.mkdir()
        (subs / 'ep01.srt').write_text('x')
        voca.preview = False
        os.chdir(tmp_path)
        result = voca.rename(['ep01.mkv'], ['01 Pilot.mkv'],
                             True, ['ep01.srt'], ['01 Pilot.srt'])
        assert result is False
        assert (subs / '01 Pilot.srt').exists()
        assert not (subs / 'ep01.srt').exists()


# ── log ───────────────────────────────────────────────────────────────────────

class TestLog:
    def test_creates_log_file_and_directory(self, tmp_log):
        log_dir, log_file = tmp_log
        voca.log('/show/S01', ['ep1.mkv', 'ep2.mkv'], ['01 A.mkv', '02 B.mkv'])
        assert log_file.exists()
        data = json.loads(log_file.read_text())
        assert data['/show/S01'] == {'ep1.mkv': '01 A.mkv', 'ep2.mkv': '02 B.mkv'}

    def test_preserves_other_entries(self, tmp_log):
        log_dir, log_file = tmp_log
        voca.log('/show/S01', ['a.mkv'], ['01 A.mkv'])
        voca.log('/show/S02', ['b.mkv'], ['01 B.mkv'])
        data = json.loads(log_file.read_text())
        assert '/show/S01' in data
        assert '/show/S02' in data

    def test_overwrites_same_directory_entry(self, tmp_log):
        log_dir, log_file = tmp_log
        voca.log('/show/S01', ['old.mkv'], ['01 Old.mkv'])
        voca.log('/show/S01', ['new.mkv'], ['01 New.mkv'])
        data = json.loads(log_file.read_text())
        assert data['/show/S01'] == {'new.mkv': '01 New.mkv'}

    def test_handles_corrupted_log_gracefully(self, tmp_log):
        log_dir, log_file = tmp_log
        log_dir.mkdir()
        log_file.write_text('NOT JSON')
        voca.log('/show/S01', ['a.mkv'], ['01 A.mkv'])
        data = json.loads(log_file.read_text())
        assert '/show/S01' in data


# ── undo ──────────────────────────────────────────────────────────────────────

class TestUndo:
    @pytest.fixture(autouse=True)
    def _restore(self, restore_cwd):
        pass

    def test_reverses_rename(self, tmp_path, tmp_log):
        log_dir, log_file = tmp_log
        (tmp_path / '01 Pilot.mkv').write_text('x')
        log_dir.mkdir()
        log_file.write_text(json.dumps(
            {str(tmp_path): {'ep01.mkv': '01 Pilot.mkv'}}
        ))
        voca.undo(str(tmp_path))
        assert (tmp_path / 'ep01.mkv').exists()
        assert not (tmp_path / '01 Pilot.mkv').exists()

    def test_removes_entry_from_log_after_undo(self, tmp_path, tmp_log):
        log_dir, log_file = tmp_log
        (tmp_path / '01 Pilot.mkv').write_text('x')
        log_dir.mkdir()
        log_file.write_text(json.dumps(
            {str(tmp_path): {'ep01.mkv': '01 Pilot.mkv'}}
        ))
        voca.undo(str(tmp_path))
        assert str(tmp_path) not in json.loads(log_file.read_text())

    def test_preserves_other_entries_after_undo(self, tmp_path, tmp_log):
        log_dir, log_file = tmp_log
        (tmp_path / '01 Pilot.mkv').write_text('x')
        log_dir.mkdir()
        log_file.write_text(json.dumps({
            str(tmp_path): {'ep01.mkv': '01 Pilot.mkv'},
            '/other/dir': {'x.mkv': '01 X.mkv'},
        }))
        voca.undo(str(tmp_path))
        assert '/other/dir' in json.loads(log_file.read_text())

    def test_no_log_file_exits(self, tmp_path, tmp_log):
        with pytest.raises(SystemExit):
            voca.undo(str(tmp_path))

    def test_directory_not_in_log_exits(self, tmp_path, tmp_log):
        log_dir, log_file = tmp_log
        log_dir.mkdir()
        log_file.write_text(json.dumps({'/other': {'a.mkv': 'b.mkv'}}))
        with pytest.raises(SystemExit):
            voca.undo(str(tmp_path))

    def test_missing_renamed_file_warns(self, tmp_path, tmp_log, capsys):
        log_dir, log_file = tmp_log
        log_dir.mkdir()
        # '01 Pilot.mkv' was already deleted or moved — undo should warn, not crash
        log_file.write_text(json.dumps(
            {str(tmp_path): {'ep01.mkv': '01 Pilot.mkv'}}
        ))
        voca.undo(str(tmp_path))
        assert 'Warning' in capsys.readouterr().out


# ── scrape_page ───────────────────────────────────────────────────────────────

class TestScrapePage:
    def _resp(self, payload):
        r = MagicMock()
        r.raise_for_status.return_value = None
        r.json.return_value = payload
        return r

    def test_returns_parsed_json(self):
        with patch.object(voca.SESSION, 'get', return_value=self._resp({'id': 1})):
            assert voca.scrape_page('https://x.com') == {'id': 1}

    def test_passes_params_to_get(self):
        with patch.object(voca.SESSION, 'get', return_value=self._resp([])) as m:
            voca.scrape_page('https://x.com', params={'q': 'test'})
        m.assert_called_once_with('https://x.com', params={'q': 'test'}, timeout=10)

    def test_retries_once_on_timeout(self):
        with patch.object(voca.SESSION, 'get', side_effect=[
            requests.exceptions.Timeout(),
            self._resp({'ok': True}),
        ]):
            assert voca.scrape_page('https://x.com') == {'ok': True}

    def test_exits_after_three_timeouts(self):
        with patch.object(voca.SESSION, 'get',
                          side_effect=requests.exceptions.Timeout()):
            with pytest.raises(SystemExit):
                voca.scrape_page('https://x.com')

    def test_exits_on_connection_error(self):
        with patch.object(voca.SESSION, 'get',
                          side_effect=requests.exceptions.ConnectionError()):
            with pytest.raises(SystemExit):
                voca.scrape_page('https://x.com')

    def test_exits_on_invalid_json(self):
        r = self._resp(None)
        r.json.side_effect = ValueError('bad json')
        with patch.object(voca.SESSION, 'get', return_value=r):
            with pytest.raises(SystemExit):
                voca.scrape_page('https://x.com')

    def test_exits_on_http_error(self):
        with patch.object(voca.SESSION, 'get',
                          side_effect=requests.exceptions.RequestException()):
            with pytest.raises(SystemExit):
                voca.scrape_page('https://x.com')


# ── get_episodes (caching) ────────────────────────────────────────────────────

class TestGetEpisodesCache:
    def test_caches_result_for_same_id(self):
        eps = [{'season': 1, 'number': 1, 'name': 'Pilot'}]
        with patch.object(voca, 'scrape_page', return_value=eps) as m:
            voca.get_episodes(42)
            voca.get_episodes(42)
        m.assert_called_once()

    def test_fetches_separately_for_different_ids(self):
        with patch.object(voca, 'scrape_page', return_value=[]) as m:
            voca.get_episodes(10)
            voca.get_episodes(20)
        assert m.call_count == 2


# ── get_titles ────────────────────────────────────────────────────────────────

class TestGetTitles:
    _EPS = [
        {'season': 1, 'number': 1, 'name': 'Pilot'},
        {'season': 1, 'number': 2, 'name': 'Second'},
        {'season': 2, 'number': 1, 'name': 'S2 Pilot'},
    ]

    def test_returns_titles_for_correct_season(self):
        with patch.object(voca, 'get_episodes', return_value=self._EPS):
            assert voca.get_titles(1, 1) == ['Pilot', 'Second']

    def test_returns_titles_for_season_2(self):
        with patch.object(voca, 'get_episodes', return_value=self._EPS):
            assert voca.get_titles(1, 2) == ['S2 Pilot']

    def test_missing_season_returns_empty_list(self):
        with patch.object(voca, 'get_episodes', return_value=self._EPS):
            assert voca.get_titles(1, 99) == []

    def test_none_episode_name_becomes_untitled(self):
        with patch.object(voca, 'get_episodes',
                          return_value=[{'season': 1, 'number': 1, 'name': None}]):
            assert voca.get_titles(1, 1) == ['Untitled']

    def test_empty_episode_name_becomes_untitled(self):
        with patch.object(voca, 'get_episodes',
                          return_value=[{'season': 1, 'number': 1, 'name': ''}]):
            assert voca.get_titles(1, 1) == ['Untitled']

    def test_title_with_forbidden_chars_sanitized(self):
        with patch.object(voca, 'get_episodes',
                          return_value=[{'season': 1, 'number': 1, 'name': 'A/B: C'}]):
            result = voca.get_titles(1, 1)
        assert '/' not in result[0]
        assert ':' not in result[0]


# ── get_show_data HTML stripping ──────────────────────────────────────────────

class TestGetShowDataHtml:
    def _raw(self, summary):
        return {
            'name': 'Show', 'language': 'English', 'genres': ['Drama'],
            'id': 1, 'premiered': '2000-01-01',
            'network': {'name': 'Net', 'country': {'name': 'USA'}},
            'summary': summary,
        }

    def test_strips_p_tags(self):
        with patch.object(voca, 'scrape_page', return_value=self._raw('<p>Hello</p>')):
            data = voca.get_show_data(1)
        assert '<p>' not in data['summary'] and 'Hello' in data['summary']

    def test_converts_bold_to_ansi(self):
        with patch.object(voca, 'scrape_page', return_value=self._raw('<b>Bold</b>')):
            data = voca.get_show_data(1)
        assert '\033[1m' in data['summary'] and '\033[0m' in data['summary']

    def test_replaces_html_entities(self):
        with patch.object(voca, 'scrape_page',
                          return_value=self._raw('a&amp;b&nbsp;c')):
            data = voca.get_show_data(1)
        assert '&amp;' not in data['summary']
        assert '&nbsp;' not in data['summary']
        assert '&' in data['summary']

    def test_none_summary_returns_placeholder(self):
        with patch.object(voca, 'scrape_page', return_value=self._raw(None)):
            data = voca.get_show_data(1)
        assert data['summary'] == 'No summary available'

    def test_online_show_uses_webchannel(self):
        raw = self._raw(None)
        raw['network'] = None
        raw['webChannel'] = {'name': 'Netflix'}
        with patch.object(voca, 'scrape_page', return_value=raw):
            data = voca.get_show_data(1)
        assert data['country'] == 'Online'
        assert data['network'] == 'Netflix'


# ── get_old_names ─────────────────────────────────────────────────────────────

class TestGetOldNames:
    @pytest.fixture(autouse=True)
    def _restore(self, restore_cwd):
        pass

    def test_returns_sorted_video_files(self, tmp_path):
        for f in ['ep03.mkv', 'ep01.mkv', 'ep02.mkv']:
            (tmp_path / f).write_text('x')
        voca.filetype = None
        result, ext = voca.get_old_names(str(tmp_path))
        assert result == ['ep01.mkv', 'ep02.mkv', 'ep03.mkv']
        assert ext == '.mkv'

    def test_ignores_non_video_files(self, tmp_path):
        (tmp_path / 'ep01.mkv').write_text('x')
        (tmp_path / 'cover.jpg').write_text('x')
        voca.filetype = None
        result, _ = voca.get_old_names(str(tmp_path))
        assert 'cover.jpg' not in result and 'ep01.mkv' in result

    def test_jumbled_sorts_numerically(self, tmp_path):
        for f in ['ep10.mkv', 'ep2.mkv', 'ep1.mkv']:
            (tmp_path / f).write_text('x')
        voca.filetype = None
        voca.jumbled = True
        result, _ = voca.get_old_names(str(tmp_path))
        assert result == ['ep1.mkv', 'ep2.mkv', 'ep10.mkv']

    def test_empty_directory_returns_empty(self, tmp_path):
        voca.filetype = None
        result, ext = voca.get_old_names(str(tmp_path))
        assert result == [] and ext is None


# ── execute (integration) ─────────────────────────────────────────────────────

class TestExecute:
    @pytest.fixture(autouse=True)
    def _restore(self, restore_cwd):
        pass

    _SHOW = {
        'series': 'Test', 'id': 1, 'language': 'English',
        'genre': 'Drama', 'premiere': '2000', 'country': 'USA',
        'network': 'Net', 'summary': 'x',
    }

    def test_renames_files_to_titles(self, tmp_path, tmp_log):
        sd = tmp_path / 'Season 01'
        sd.mkdir()
        for i in range(1, 4):
            (sd / f'ep{i:02d}.mkv').write_text('x')
        voca.preview = False
        voca.filetype = None
        with patch.object(voca, 'get_titles',
                          return_value=['Pilot', 'Second Ep', 'Third Ep']):
            voca.execute(str(sd), 1, 1)
        assert (sd / '01 Pilot.mkv').exists()
        assert (sd / '02 Second Ep.mkv').exists()
        assert (sd / '03 Third Ep.mkv').exists()

    def test_skips_empty_directory(self, tmp_path, capsys):
        sd = tmp_path / 'Season 01'
        sd.mkdir()
        with patch.object(voca, 'get_titles', return_value=['Pilot']):
            voca.execute(str(sd), 1, 1)
        assert 'No valid files' in capsys.readouterr().out

    def test_writes_log_on_success(self, tmp_path, tmp_log):
        log_dir, log_file = tmp_log
        sd = tmp_path / 'Season 01'
        sd.mkdir()
        (sd / 'ep01.mkv').write_text('x')
        voca.preview = False
        voca.filetype = None
        voca.enable_backup_log = True
        with patch.object(voca, 'get_titles', return_value=['Pilot']):
            voca.execute(str(sd), 1, 1)
        assert log_file.exists()
        assert str(sd) in json.loads(log_file.read_text())

    def test_no_log_when_backup_disabled(self, tmp_path, tmp_log):
        log_dir, log_file = tmp_log
        sd = tmp_path / 'Season 01'
        sd.mkdir()
        (sd / 'ep01.mkv').write_text('x')
        voca.preview = False
        voca.filetype = None
        voca.enable_backup_log = False
        with patch.object(voca, 'get_titles', return_value=['Pilot']):
            voca.execute(str(sd), 1, 1)
        assert not log_file.exists()

    def test_reports_too_many_files(self, tmp_path, capsys):
        sd = tmp_path / 'Season 01'
        sd.mkdir()
        for i in range(1, 4):
            (sd / f'ep{i:02d}.mkv').write_text('x')
        voca.preview = False
        voca.filetype = None
        with patch.object(voca, 'get_titles', return_value=['Pilot']), \
                patch.object(voca, 'get_show_data', return_value=self._SHOW):
            voca.execute(str(sd), 1, 1)
        assert 'More files' in capsys.readouterr().out

    def test_reports_too_few_files(self, tmp_path, capsys):
        sd = tmp_path / 'Season 01'
        sd.mkdir()
        (sd / 'ep01.mkv').write_text('x')
        voca.preview = False
        voca.filetype = None
        with patch.object(voca, 'get_titles',
                          return_value=['Ep1', 'Ep2', 'Ep3']), \
                patch.object(voca, 'get_show_data', return_value=self._SHOW):
            voca.execute(str(sd), 1, 1)
        assert 'Fewer files' in capsys.readouterr().out

    def test_preview_does_not_rename(self, tmp_path, tmp_log):
        sd = tmp_path / 'Season 01'
        sd.mkdir()
        (sd / 'ep01.mkv').write_text('x')
        voca.preview = True
        voca.filetype = None
        with patch.object(voca, 'get_titles', return_value=['Pilot']):
            voca.execute(str(sd), 1, 1)
        assert (sd / 'ep01.mkv').exists()
        assert not (sd / '01 Pilot.mkv').exists()

    def test_mixed_filetypes_each_keeps_extension(self, tmp_path, tmp_log):
        sd = tmp_path / 'Season 01'
        sd.mkdir()
        (sd / 'ep01.mkv').write_text('x')
        (sd / 'ep02.mp4').write_text('x')
        voca.preview = False
        voca.filetype = None
        with patch.object(voca, 'get_titles', return_value=['Pilot', 'Second']):
            voca.execute(str(sd), 1, 1)
        assert (sd / '01 Pilot.mkv').exists()
        assert (sd / '02 Second.mp4').exists()
