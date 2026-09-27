/// Browser file download of a URL (the backend sends
/// `Content-Disposition: attachment`). Returns false where there is no
/// browser (tests, desktop).
library;

export 'download_stub.dart' if (dart.library.js_interop) 'download_web.dart';
