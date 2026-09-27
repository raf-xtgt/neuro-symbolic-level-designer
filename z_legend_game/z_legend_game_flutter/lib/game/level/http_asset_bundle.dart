import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

/// An [AssetBundle] that fetches keys over HTTP relative to [baseUrl].
///
/// Flutter's built-in network bundle uses the native IO HTTP client, which
/// does not exist on the web. `package:http` uses the browser's fetch there.
class HttpAssetBundle extends CachingAssetBundle {
  HttpAssetBundle(Uri baseUrl, {http.Client? client})
    : baseUrl = baseUrl.path.endsWith('/')
          ? baseUrl
          : baseUrl.replace(path: '${baseUrl.path}/'),
      _client = client ?? http.Client();

  /// Folder URL that keys are resolved against. Always ends with `/`.
  final Uri baseUrl;

  final http.Client _client;

  @override
  Future<ByteData> load(String key) async {
    final url = baseUrl.resolve(key);
    final response = await _client.get(url);
    if (response.statusCode != 200) {
      throw FlutterError(
        'HttpAssetBundle: GET $url returned status ${response.statusCode}.',
      );
    }
    return ByteData.sublistView(response.bodyBytes);
  }

  @override
  String toString() => '${describeIdentity(this)}($baseUrl)';
}
