import 'dart:convert';

import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

import 'models.dart';

/// Client for the level generation backend (ARCHITECTURE.md section 8).
class LevelApi {
  LevelApi(this.baseUrl, {http.Client? client})
    : _client = client ?? http.Client();

  /// Reads `apiUrl` from `assets/config.json`.
  static Future<LevelApi> fromConfig({AssetBundle? bundle}) async {
    final config = jsonDecode(
      await (bundle ?? rootBundle).loadString('assets/config.json'),
    );
    return LevelApi(Uri.parse(config['apiUrl'] as String));
  }

  /// E.g. `http://localhost:8000`.
  final Uri baseUrl;
  final http.Client _client;

  Uri _url(String path) => baseUrl.resolve(path);

  /// `<apiUrl>/api/levels/<jobId>/bundle/`.
  Uri bundleUrl(String jobId) => _url('/api/levels/$jobId/bundle/');

  Future<List<AssetPack>> listAssetPacks() async {
    final response = await _send(() => _client.get(_url('/api/asset-packs')));
    return (_decode(response) as List)
        .map((p) => AssetPack.fromJson(p as Map<String, dynamic>))
        .toList();
  }

  Future<CreateJobResult> createLevel(LevelRequest request) async {
    final multipart = http.MultipartRequest('POST', _url('/api/levels'))
      ..fields['prompt'] = request.prompt
      ..fields['planner'] = request.planner.id;
    if (request.assetPack != null) {
      multipart.fields['asset_pack'] = request.assetPack!;
    }
    void addFiles(String field, List<LevelFile> files) {
      for (final f in files) {
        multipart.files.add(
          http.MultipartFile.fromBytes(field, f.bytes, filename: f.name),
        );
      }
    }

    addFiles('spritesheets', request.spritesheets);
    addFiles('tilesets', request.tilesets);
    addFiles('maps', request.maps);

    final response = await _send(
      () async => http.Response.fromStream(await _client.send(multipart)),
    );
    return CreateJobResult.fromJson(_decode(response) as Map<String, dynamic>);
  }

  Future<JobStatus> getJob(String jobId) async {
    final response = await _send(
      () => _client.get(_url('/api/levels/$jobId')),
    );
    return JobStatus.fromJson(_decode(response) as Map<String, dynamic>);
  }

  /// Downloads one bundle file, e.g. `preview_level.png`.
  Future<Uint8List> getBundleFile(String jobId, String name) async {
    final response = await _send(
      () => _client.get(bundleUrl(jobId).resolve(name)),
    );
    if (response.statusCode != 200) {
      throw ApiException(response.statusCode, 'GET $name failed');
    }
    return response.bodyBytes;
  }

  Future<http.Response> _send(Future<http.Response> Function() request) async {
    try {
      return await request();
    } on http.ClientException catch (e) {
      throw ApiUnavailableException(baseUrl, e);
    }
  }

  Object? _decode(http.Response response) {
    if (response.statusCode == 422) {
      final body = jsonDecode(response.body) as Map<String, dynamic>;
      throw ApiValidationException(
        (body['errors'] as List)
            .map((e) => FieldError.fromJson(e as Map<String, dynamic>))
            .toList(),
      );
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(response.statusCode, response.body);
    }
    return jsonDecode(response.body);
  }
}
