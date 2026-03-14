"""Tests for ECRRepository and ECRImage."""

from unittest import mock

import pytest
from botocore.exceptions import ClientError

from infrahouse_core.aws.ecr_repository import ECRImage, ECRRepository

REPO_NAME = "my-service"


def _make_client_error(code, message="test"):
    """Helper to create a ClientError with a specific error code."""
    return ClientError({"Error": {"Code": code, "Message": message}}, "test_operation")


# -- ECRImage constructor validation ------------------------------------------


def test_ecr_image_requires_tag_or_digest():
    """ECRImage raises ValueError when neither tag nor digest is given."""
    with pytest.raises(ValueError, match="Either tag or digest"):
        ECRImage(mock.MagicMock(), REPO_NAME)


def test_ecr_image_rejects_both_tag_and_digest():
    """ECRImage raises ValueError when both tag and digest are given."""
    with pytest.raises(ValueError, match="either tag or digest"):
        ECRImage(mock.MagicMock(), REPO_NAME, tag="latest", digest="sha256:abc")


# -- ECRImage._image_id ------------------------------------------------------


def test_ecr_image_id_from_tag():
    """_image_id returns imageTag dict when constructed with tag."""
    image = ECRImage(mock.MagicMock(), REPO_NAME, tag="latest")
    assert image._image_id == {"imageTag": "latest"}


def test_ecr_image_id_from_digest():
    """_image_id returns imageDigest dict when constructed with digest."""
    image = ECRImage(mock.MagicMock(), REPO_NAME, digest="sha256:abc123")
    assert image._image_id == {"imageDigest": "sha256:abc123"}


# -- ECRImage.exists ---------------------------------------------------------


def test_image_exists_true():
    """ECRImage.exists returns True when the image is found."""
    mock_client = mock.MagicMock()
    mock_client.describe_images.return_value = {
        "imageDetails": [{"imageDigest": "sha256:abc", "imageTags": ["latest"]}]
    }
    image = ECRImage(mock_client, REPO_NAME, tag="latest")
    assert image.exists is True
    mock_client.describe_images.assert_called_once_with(
        repositoryName=REPO_NAME,
        imageIds=[{"imageTag": "latest"}],
    )


def test_image_exists_false():
    """ECRImage.exists returns False when ImageNotFoundException is raised."""
    mock_client = mock.MagicMock()
    mock_client.describe_images.side_effect = _make_client_error("ImageNotFoundException")
    image = ECRImage(mock_client, REPO_NAME, tag="nonexistent")
    assert image.exists is False


def test_image_exists_unexpected_error():
    """Unexpected errors from describe_images are re-raised."""
    mock_client = mock.MagicMock()
    mock_client.describe_images.side_effect = _make_client_error("AccessDeniedException")
    image = ECRImage(mock_client, REPO_NAME, tag="latest")
    with pytest.raises(ClientError) as exc_info:
        _ = image.exists
    assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"


# -- ECRImage.tags ------------------------------------------------------------


def test_image_tags():
    """ECRImage.tags returns the list of tags from describe_images."""
    mock_client = mock.MagicMock()
    mock_client.describe_images.return_value = {
        "imageDetails": [{"imageTags": ["latest", "v1.0", "deployed-at-20260314"], "imageDigest": "sha256:abc"}]
    }
    image = ECRImage(mock_client, REPO_NAME, tag="latest")
    assert image.tags == ["latest", "v1.0", "deployed-at-20260314"]


def test_image_tags_not_found():
    """ECRImage.tags returns empty list when image is not found."""
    mock_client = mock.MagicMock()
    mock_client.describe_images.side_effect = _make_client_error("ImageNotFoundException")
    image = ECRImage(mock_client, REPO_NAME, tag="nonexistent")
    assert image.tags == []


def test_image_tags_no_tags():
    """ECRImage.tags returns empty list when image has no tags (untagged image)."""
    mock_client = mock.MagicMock()
    mock_client.describe_images.return_value = {"imageDetails": [{"imageDigest": "sha256:abc"}]}
    image = ECRImage(mock_client, REPO_NAME, digest="sha256:abc")
    assert image.tags == []


# -- ECRImage.digest ----------------------------------------------------------


def test_image_digest():
    """ECRImage.digest returns the digest from describe_images."""
    mock_client = mock.MagicMock()
    mock_client.describe_images.return_value = {
        "imageDetails": [{"imageDigest": "sha256:abc123", "imageTags": ["latest"]}]
    }
    image = ECRImage(mock_client, REPO_NAME, tag="latest")
    assert image.digest == "sha256:abc123"


def test_image_digest_not_found():
    """ECRImage.digest returns None when image is not found."""
    mock_client = mock.MagicMock()
    mock_client.describe_images.side_effect = _make_client_error("ImageNotFoundException")
    image = ECRImage(mock_client, REPO_NAME, tag="nonexistent")
    assert image.digest is None


# -- ECRRepository.repository_name --------------------------------------------


def test_repository_name():
    """repository_name returns the name passed to the constructor."""
    repo = ECRRepository(REPO_NAME)
    assert repo.repository_name == REPO_NAME


# -- ECRRepository.exists ----------------------------------------------------


def test_repo_exists_true():
    """exists returns True when the repository is found."""
    repo = ECRRepository(REPO_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_repositories.return_value = {"repositories": [{"repositoryName": REPO_NAME}]}

    with mock.patch.object(ECRRepository, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert repo.exists is True
        mock_client.describe_repositories.assert_called_once_with(repositoryNames=[REPO_NAME])


def test_repo_exists_false():
    """exists returns False when RepositoryNotFoundException is raised."""
    repo = ECRRepository(REPO_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_repositories.side_effect = _make_client_error("RepositoryNotFoundException")

    with mock.patch.object(ECRRepository, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert repo.exists is False


def test_repo_exists_unexpected_error():
    """Unexpected errors from describe_repositories are re-raised."""
    repo = ECRRepository(REPO_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_repositories.side_effect = _make_client_error("AccessDeniedException")

    with mock.patch.object(ECRRepository, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            _ = repo.exists
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"


# -- ECRRepository.repository_uri --------------------------------------------


def test_repository_uri():
    """repository_uri returns the URI from describe_repositories."""
    repo = ECRRepository(REPO_NAME, region="us-west-2")
    mock_client = mock.MagicMock()
    expected_uri = "123456789012.dkr.ecr.us-west-2.amazonaws.com/my-service"
    mock_client.describe_repositories.return_value = {"repositories": [{"repositoryUri": expected_uri}]}

    with mock.patch.object(ECRRepository, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert repo.repository_uri == expected_uri


# -- ECRRepository.get_image -------------------------------------------------


def test_get_image_by_tag():
    """get_image returns an ECRImage that queries by tag."""
    repo = ECRRepository(REPO_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_images.return_value = {
        "imageDetails": [{"imageTags": ["latest", "v1.0"], "imageDigest": "sha256:abc"}]
    }

    with mock.patch.object(ECRRepository, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        image = repo.get_image(tag="latest")
        assert isinstance(image, ECRImage)
        assert image.tags == ["latest", "v1.0"]


def test_get_image_by_digest():
    """get_image returns an ECRImage that queries by digest."""
    repo = ECRRepository(REPO_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.describe_images.return_value = {
        "imageDetails": [{"imageTags": ["latest"], "imageDigest": "sha256:abc"}]
    }

    with mock.patch.object(ECRRepository, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        image = repo.get_image(digest="sha256:abc")
        assert isinstance(image, ECRImage)
        assert image.tags == ["latest"]


# -- ECRRepository.images ----------------------------------------------------


def _mock_paginator(pages):
    """Return a mock paginator that yields the given pages."""
    paginator = mock.MagicMock()
    paginator.paginate.return_value = iter(pages)
    return paginator


def test_images_returns_ecr_image_list():
    """images property returns a list of ECRImage objects from paginated results."""
    repo = ECRRepository(REPO_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator(
        [
            {
                "imageDetails": [
                    {"imageDigest": "sha256:aaa", "imageTags": ["latest"]},
                    {"imageDigest": "sha256:bbb", "imageTags": ["v1.0"]},
                ]
            },
            {
                "imageDetails": [
                    {"imageDigest": "sha256:ccc", "imageTags": ["v0.9"]},
                ]
            },
        ]
    )

    with mock.patch.object(ECRRepository, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        images = repo.images
        assert len(images) == 3
        assert all(isinstance(img, ECRImage) for img in images)


def test_images_empty_repo():
    """images property returns empty list for a repo with no images."""
    repo = ECRRepository(REPO_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.get_paginator.return_value = _mock_paginator([{"imageDetails": []}])

    with mock.patch.object(ECRRepository, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        assert repo.images == []


# -- ECRRepository.delete ----------------------------------------------------


def test_delete_repository():
    """delete() calls delete_repository with force=True."""
    repo = ECRRepository(REPO_NAME, region="us-east-1")
    mock_client = mock.MagicMock()

    with mock.patch.object(ECRRepository, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        repo.delete()

    mock_client.delete_repository.assert_called_once_with(repositoryName=REPO_NAME, force=True)


def test_delete_not_exists():
    """delete() on a non-existent repository is a no-op."""
    repo = ECRRepository(REPO_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_repository.side_effect = _make_client_error("RepositoryNotFoundException")

    with mock.patch.object(ECRRepository, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        repo.delete()  # Should not raise


def test_delete_unexpected_error():
    """delete() re-raises unexpected errors."""
    repo = ECRRepository(REPO_NAME, region="us-east-1")
    mock_client = mock.MagicMock()
    mock_client.delete_repository.side_effect = _make_client_error("AccessDeniedException")

    with mock.patch.object(ECRRepository, "_client", new_callable=mock.PropertyMock, return_value=mock_client):
        with pytest.raises(ClientError) as exc_info:
            repo.delete()
        assert exc_info.value.response["Error"]["Code"] == "AccessDeniedException"
