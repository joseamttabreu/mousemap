paths = {'BINDIR': bindir, 'LIBEXECDIR': libexecdir}

configure_file(input: 'mousemapd.service.in', output: 'mousemapd.service',
  configuration: paths, install_dir: prefix / 'lib' / 'systemd' / 'user')

configure_file(input: 'io.github.mousemap.Daemon.service.in', output: 'io.github.mousemap.Daemon.service',
  configuration: paths, install_dir: datadir / 'dbus-1' / 'services')

desktop = configure_file(input: 'io.github.mousemap.desktop.in', output: 'io.github.mousemap.desktop',
  configuration: paths, install_dir: datadir / 'applications')

configure_file(input: 'io.github.mousemap.policy.in', output: 'io.github.mousemap.policy',
  configuration: paths, install_dir: datadir / 'polkit-1' / 'actions')

install_data('io.github.mousemap.metainfo.xml', install_dir: datadir / 'metainfo')
install_data('io.github.mousemap.svg', install_dir: datadir / 'icons' / 'hicolor' / 'scalable' / 'apps')
install_data('70-mousemap.rules', install_dir: prefix / 'lib' / 'udev' / 'rules.d')
install_data('modules-load.conf', rename: 'mousemap.conf', install_dir: prefix / 'lib' / 'modules-load.d')
install_data('mousemap-setup', install_dir: libexecdir, install_mode: 'rwxr-xr-x')

desktop_validate = find_program('desktop-file-validate', required: false)
if desktop_validate.found()
  test('desktop-file', desktop_validate, args: [desktop])
endif

appstreamcli = find_program('appstreamcli', required: false)
if appstreamcli.found()
  test('metainfo', appstreamcli,
    args: ['validate', '--no-net', '--explain', files('io.github.mousemap.metainfo.xml')])
endif
