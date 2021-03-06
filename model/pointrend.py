
import torch
import torch.nn as nn
import torch.nn.functional as F

from . import sampling_points


class PointHead(nn.Module):
    def __init__(self, in_c=533, num_classes=21, k=3, beta=0.75):
        super().__init__()
        self.mlp = nn.Conv1d(533, 21, 1)
        self.k = k
        self.beta = beta

    def forward(self, x, res2, out):
        """
        1. Fine-grained features are interpolated from res2 for DeeplabV3
        2. During training we sample as many points as there are on a stride 16 feature map of the input
        3. To measure prediction uncertainty
           we use the same strategy during training and inference: the difference between the most
           confident and second most confident class probabilities.
        """
        if not self.training:
            return self.inference(x, res2, out)

        B = x.shape[0]

        stride = x.shape[-1] // out.shape[-1]

        # Shape :B, num_points, 2
        points = sampling_points(out, self.k, self.beta)

        C = out.shape[1]
        coarse = torch.gather(out.view(B, C, -1), 2,
                              points.unsqueeze(1).expand(-1, C, -1))

        C = res2.shape[1]
        fine = torch.gather(res2.view(B, C, -1), 2,
                            points.unsqueeze(1).expand(-1, C, -1))

        feature_representation = torch.cat([coarse, fine], dim=1)

        rend = self.mlp(feature_representation)

        return {"rend": rend, "points": points}

    @torch.no_grad()
    def inference(self, x, res2, out):
        while out.shape[-1] != x.shape[-1]:
            stride = x.shape[-1] // out.shape[-1]
            N = out.shape[-2] * out.shape[-1]
            out = F.interpolate(out, scale_factor=2, mode="bilinear", align_corners=True)

            points = sampling_points(out, training=False, N=4048)

            C = out.shape[1]
            coarse = torch.gather(out.view(B, C, -1), 2,
                                  points.unsqueeze(1).expand(-1, C, -1))

            C = res2.shape[1]
            fine = torch.gather(res2.view(B, C, -1), 2,
                                points.unsqueeze(1).expand(-1, C, -1))
            feature_representation = torch.cat([coarse, fine], dim=1)

            rend = self.mlp(feature_representation)

            # From Issues #5
            B, C, H, W = out.shape
            out = out.view(B, C, -1).scatter_(2, points.unsqueeze(1).expand(-1, C, -1), rend)
            out = out.reshape((B, C, H, W))

        return {"fine": out}


class PointRend(nn.Module):
    def __init__(self, backbone, head):
        super().__init__()
        self.backbone = backbone
        self.head = head

    def forward(self, x):
        result = self.backbone(x)
        head = self.head(x, result["res2"], result["coarse"])
        return {**result, **head}


if __name__ == "__main__":
    x = torch.randn(3, 3, 256, 512).cuda()
    from deeplab import deeplabv3
    net = PointRend(deeplabv3(False), PointHead()).cuda()
    out = net(x)
    for k, v in out.items():
        print(k, v.shape)
