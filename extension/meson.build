uuid = 'mousemap@joseamttabreu.github.com'
extension_dir = datadir / 'gnome-shell' / 'extensions' / uuid

configure_file(input: 'metadata.json.in', output: 'metadata.json',
  configuration: {'VERSION': meson.project_version()}, install_dir: extension_dir)
install_data('extension.js', 'focus.js', install_dir: extension_dir)
