// mousemap: perfis por aplicativo. Informa o aplicativo em foco ao mousemapd.

import Shell from 'gi://Shell';
import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';

import {FocusReporter} from './focus.js';

export default class MousemapExtension extends Extension {
    enable() {
        this._reporter = new FocusReporter(global.display, Shell.WindowTracker.get_default());
        this._reporter.start();
        this._reporter.report(true);
    }

    disable() {
        this._reporter.stop();
        this._reporter = null;
    }
}
