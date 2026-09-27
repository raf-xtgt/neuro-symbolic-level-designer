import 'package:web/web.dart' as web;

/// Clicks a temporary `<a href download>` so the browser saves the file.
Future<bool> downloadUrl(Uri url, String fileName) async {
  final anchor = web.HTMLAnchorElement()
    ..href = url.toString()
    ..download = fileName;
  web.document.body?.append(anchor);
  anchor.click();
  anchor.remove();
  return true;
}
